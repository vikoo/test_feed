from cron.moto_gp.moto_gp_api import fetch_season, fetch_event, fetch_session, fetch_race_results
from cron.notifiaction.notification_utils import send_race_complete_notification
from cron.stats_calc.moto_gp.moto_gp_stats_update import process_update_moto_gp_stats
from cron.strapi_api.apis import get_latest_past_race, get_race_results_for_race_event, get_season_grid_map, \
    create_race_result, update_race_result, update_config_for_race_result
from datetime import datetime, timezone
import json
import sys
import time
from loguru import logger

is_update_enabled = False

# A classification cannot be final before the session has run this long (minutes after startTime).
MIN_SESSION_MINUTES = {"FP1": 45, "PRACTICE": 60, "FP2": 30, "QNR1": 15, "QNR2": 15, "Sprint": 20, "Race": 40}
# A started session without a classification counts as "waiting" for this long, then it is given up
# (cancelled or never published), so a runner does not wait for it forever.
WAITING_WINDOW_HOURS = 8


class MissingSeasonGridError(Exception):
    def __init__(self, numbers):
        self.numbers = numbers
        super().__init__(f"no season grid for rider numbers {numbers}")


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def process(now: datetime = None) -> dict:
    """Ingest every recent session that has no rows yet. Returns what happened per session so a caller
    (weekend_runner) knows whether to keep polling. One failing session no longer stops the others."""
    now = now or datetime.now(timezone.utc)
    summary = {"ingested": [], "waiting": [], "skipped_missing_grid": [], "errors": []}
    logger.info("fetching the schedule")
    json_data = get_latest_past_race(is_f1_feed=False)

    races = json_data["data"]["races"]["data"]
    logger.info(f"Total races to process: {len(races)}")

    for race_entry in races:
        race_id = race_entry["id"]
        race_type = race_entry["attributes"]["type"]
        grand_prix = race_entry["attributes"]["grandPrix"]["data"]
        label = f'{grand_prix["attributes"].get("shortName")} {race_type} (race {race_id})'
        logger.info(f"race_id: {race_id} --- race_type: {race_type}")

        started = parse_time(race_entry["attributes"]["startTime"])
        age_minutes = (now - started).total_seconds() / 60
        if age_minutes < MIN_SESSION_MINUTES.get(race_type, 0):
            logger.info(f"{label} started {age_minutes:.0f} min ago, not finished yet")
            summary["waiting"].append(label)
            continue

        try:
            strapi_races = get_race_results_for_race_event(is_f1_feed=False, race_id=race_id)
            race_result_count = len(strapi_races['data']['raceResults']['data'])
            logger.info(f"race_result_count from strapi: {race_result_count}")

            # Build a minimal json_data-like structure scoped to this race entry
            race_json_data = {"data": {"races": {"data": [race_entry]}}}

            status = "exists"
            if not is_update_enabled:
                if race_result_count == 0:
                    moto_gp_race_results, season_grid_map, year = fetch_and_upload_race_data(race_json_data)
                    status = upload_moto_gp_race_results(moto_gp_race_results, season_grid_map, race_id, race_type, grand_prix, year)
                else:
                    logger.info("Race results already exist in Strapi. No need to fetch from MotoGP API.")
            else:
                logger.info("UPDATE is enabled")
                moto_gp_race_results, season_grid_map, year = fetch_and_upload_race_data(race_json_data)
                if race_result_count == 0:
                    status = upload_moto_gp_race_results(moto_gp_race_results, season_grid_map, race_id, race_type, grand_prix, year)
                else:
                    # Convert strapi races to driver number -> race result id mapping
                    driver_number_to_id_map = convert_strapi_races_to_driver_map(strapi_races)
                    logger.info(f"Driver number to ID map: {driver_number_to_id_map}")
                    status = upload_moto_gp_race_results(moto_gp_race_results, season_grid_map, race_id, race_type, grand_prix, year, driver_number_to_id_map)
        except MissingSeasonGridError as e:
            logger.error(f"{label} NOT ingested, nothing written: {e}. Create or un-old the season grid, then rerun.")
            summary["skipped_missing_grid"].append(f"{label}: {e.numbers}")
            continue
        except Exception as e:
            logger.exception(f"{label} failed: {type(e).__name__}: {e}")
            summary["errors"].append(f"{label}: {type(e).__name__}: {e}")
            continue

        if status == "ingested":
            summary["ingested"].append(label)
        elif status == "no_classification" and age_minutes < WAITING_WINDOW_HOURS * 60:
            summary["waiting"].append(label)

    logger.info(f"summary: {summary}")
    return summary


def fetch_and_upload_race_data(json_data):
    """Fetch race data from MotoGP API and upload the results"""
    year = json_data["data"]["races"]["data"][0]["attributes"]["grandPrix"]["data"]["attributes"]["season"]["data"]["attributes"]["year"]
    event_name = json_data["data"]["races"]["data"][0]["attributes"]["grandPrix"]["data"]["attributes"]["shortName"]
    session_type = json_data["data"]["races"]["data"][0]["attributes"]["type"]
    logger.info(f"year: {year}, event_name: {event_name}, session_type: {session_type}")
    season_uuid = fetch_season(year)
    logger.info(f"season_uuid: {season_uuid}")
    event_uuid = fetch_event(event_name=event_name, season_uuid=season_uuid)
    logger.info(f"event_uuid: {event_uuid}")
    session_uuid = fetch_session(session_type=session_type, event_uuid=event_uuid)
    logger.info(f"session_uuid: {session_uuid}")
    moto_gp_race_results = fetch_race_results(session_uuid)
    season_grid_map = get_season_grid_map(is_f1_feed=False, season=year, fill_from_old_grids=True)
    return moto_gp_race_results, season_grid_map, year

def convert_strapi_races_to_driver_map(strapi_races):
    """
    Convert strapi race results to a dictionary mapping driverNumber to race result id

    Args:
        strapi_races: JSON response from get_race_results_for_race_event

    Returns:
        dict: Dictionary with driverNumber as key and race result id as value
        Example: {72: '7135', 49: '7136', ...}
    """
    driver_map = {}
    race_results = strapi_races.get('data', {}).get('raceResults', {}).get('data', [])

    for result in race_results:
        result_id = result.get('id')
        driver_number = result.get('attributes', {}).get('seasonGrid', {}).get('data', {}).get('attributes', {}).get('driverNumber')

        if result_id and driver_number is not None:
            driver_map[driver_number] = result_id

    return driver_map

def upload_moto_gp_race_results(moto_gp_race_results, season_grid_map, race_id, race_type, grand_prix, year, driver_number_to_id_map=None):
    official = moto_gp_race_results.get("official", False)
    # if not official:
    #     logger.error("official results not found in MotoGP API response. skipping upload.")
    #     return

    classification = moto_gp_race_results.get("classification", [])
    records = moto_gp_race_results.get("records", [])

    fastest_lap_rider_id = None
    fastest_lap_record = None
    gp_id = grand_prix.get("id")
    logger.info(f"gp_id: {gp_id} ")
    if classification is None or len(classification) == 0:
        logger.warning("No classification data found in MotoGP API response.")
        return "no_classification"

    # Check every rider before the first write: a missing grid used to raise KeyError halfway through,
    # leaving a partial session that later runs never completed (they only ingest sessions with 0 rows).
    missing = sorted({item["rider"]["number"] for item in classification if item["rider"]["number"] not in season_grid_map})
    if missing:
        raise MissingSeasonGridError(missing)

    for record in records:
        if record.get("type") == "fastestLap":
            fastest_lap_rider_id = record.get("rider", {}).get("id")
            fastest_lap_record = record
            logger.debug(f"fastest_lap_rider_id: {fastest_lap_rider_id}")
            break

    for index, item in enumerate(classification):
        pos = item.get("position")
        pos = pos if pos is not None else (index + 1)
        result_time = item.get("time")
        if not result_time:  # Handles None, empty string, or any falsy value
            result_time = item.get("best_lap").get("time", "") if item.get("best_lap") else ""

        race_result_json = {
            "race": race_id,
            "seasonGrid": season_grid_map[item["rider"]["number"]],
            "position": pos,
            "points": item.get("points", 0),
            "laps": item.get("total_laps", 0),
            "time": result_time,
            "dnf" : item.get("status") != "INSTND",

        }
        rider_id = item["rider"]["id"]
        logger.debug(f"Processing rider_id: {rider_id} at position: {pos}")
        # Fastest lap is an in-race record only (Grand Prix Race and Sprint). The MotoGP
        # API also returns a fastestLap record for practice and qualifying, where position 1
        # is already the fastest by lap-time ranking, so without this guard the badge leaks
        # onto those sessions. Sprint has no fastestLap record in the API yet, so it stays empty.
        if race_type in ("Race", "Sprint") and item["rider"]["id"] == fastest_lap_rider_id:
            race_result_json["fastestLap"] = True
            race_result_json["fastestLapTime"] = fastest_lap_record.get("bestLap", {}).get("time", "")
            race_result_json["fastestLapNo"] = fastest_lap_record.get("bestLap", {}).get("number", 0)

        if race_type == "QNR1" and index > 1 :
            race_result_json["finalPos"] = index + 11

        logger.debug(f"race_result: {race_result_json}")
        if driver_number_to_id_map:
            row_id = driver_number_to_id_map[item["rider"]["number"]]
            logger.debug(f" row id: {row_id} for {item['rider']['number']}")
            update_race_result(is_f1_feed=False, json_str=json.dumps(race_result_json), row_id=row_id)
        else:
            create_race_result(is_f1_feed=False, json_str=json.dumps(race_result_json))

    update_config_for_race_result(is_f1_feed=False, gp_id=gp_id)
    logger.info("######################")
    logger.info(f"update stats")
    process_update_moto_gp_stats(season_year=year)
    logger.info("######################")
    # No results push after Q1: Q2 starts minutes later and its push ("Qualifying") covers both.
    if not is_update_enabled and race_type != "QNR1":
        time.sleep(30)
        logger.info(f"sending race complete notification")
        send_race_complete_notification(is_f1=False, race_type=race_type, grand_prix=grand_prix)
    return "ingested"


if __name__ == "__main__":
    result = process()
    if result["skipped_missing_grid"] or result["errors"]:
        sys.exit(1)