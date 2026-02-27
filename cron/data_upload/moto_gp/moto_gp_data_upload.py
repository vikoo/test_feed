from cron.moto_gp.moto_gp_api import fetch_season, fetch_event, fetch_session, fetch_race_results
from cron.notifiaction.notification_utils import send_race_complete_notification
from cron.strapi_api.apis import get_latest_past_race, get_race_results_for_race_event, get_season_grid_map, \
    create_race_result, update_race_result, update_config_for_race_result
import json

is_update_enabled = False


def process():
    print("fetching the schedule")
    json_data = get_latest_past_race(is_f1_feed=False)

    # Extract the year

    race_id = json_data["data"]["races"]["data"][0]["id"]
    race_type = json_data["data"]["races"]["data"][0]["attributes"]["type"]
    grand_prix = json_data["data"]["races"]["data"][0]["attributes"]["grandPrix"]["data"]
    print(f"race_id: {race_id} --- race_type: {race_type}")
    strapi_races = get_race_results_for_race_event(is_f1_feed=False, race_id=race_id)
    race_result_count = len(strapi_races['data']['raceResults']['data'])
    print(f"race_result_count from strapi: {race_result_count}")

    if not is_update_enabled:
        if race_result_count == 0:
            moto_gp_race_results, season_grid_map = fetch_and_upload_race_data(json_data)
            upload_moto_gp_race_results(moto_gp_race_results, season_grid_map, race_id, race_type, grand_prix)
        else:
            print("Race results already exist in Strapi. No need to fetch from MotoGP API.")
    else:
        print("UPDATE is enabled")
        moto_gp_race_results, season_grid_map = fetch_and_upload_race_data(json_data)
        if race_result_count == 0:
            upload_moto_gp_race_results(moto_gp_race_results, season_grid_map, race_id, race_type, grand_prix)
        else:
            # Convert strapi races to driver number -> race result id mapping
            driver_number_to_id_map = convert_strapi_races_to_driver_map(strapi_races)
            print(f"Driver number to ID map: {driver_number_to_id_map}")
            print("Race results already exist in Strapi. No need to fetch from MotoGP API.")
            upload_moto_gp_race_results(moto_gp_race_results, season_grid_map, race_id, race_type, grand_prix, driver_number_to_id_map)


def fetch_and_upload_race_data(json_data):
    """Fetch race data from MotoGP API and upload the results"""
    year = json_data["data"]["races"]["data"][0]["attributes"]["grandPrix"]["data"]["attributes"]["season"]["data"]["attributes"]["year"]
    event_name = json_data["data"]["races"]["data"][0]["attributes"]["grandPrix"]["data"]["attributes"]["shortName"]
    session_type = json_data["data"]["races"]["data"][0]["attributes"]["type"]
    print(f"year: {year}, event_name: {event_name}, session_type: {session_type}")
    season_uuid = fetch_season(year)
    print(f"season_uuid: {season_uuid}")
    event_uuid = fetch_event(event_name=event_name, season_uuid=season_uuid)
    print(f"event_uuid: {event_uuid}")
    session_uuid = fetch_session(session_type=session_type, event_uuid=event_uuid)
    print(f"session_uuid: {session_uuid}")
    moto_gp_race_results = fetch_race_results(session_uuid)
    season_grid_map = get_season_grid_map(is_f1_feed=False, season=year)
    return moto_gp_race_results, season_grid_map

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

def upload_moto_gp_race_results(moto_gp_race_results, season_grid_map, race_id, race_type, grand_prix, driver_number_to_id_map=None):
    classification = moto_gp_race_results.get("classification", [])
    records = moto_gp_race_results.get("records", [])

    fastest_lap_rider_id = None
    fastest_lap_record = None
    gp_id = grand_prix.get("id")
    print(f"gp_id: {gp_id} ")

    for record in records:
        if record.get("type") == "fastestLap":
            fastest_lap_rider_id = record.get("rider", {}).get("id")
            fastest_lap_record = record
            print(f"fastest_lap_rider_id: {fastest_lap_rider_id}")
            break

    for index, item in enumerate(classification):
        pos = item.get("position")
        pos = pos if pos is not None else (index + 1)
        time = item.get("time")
        if not time:  # Handles None, empty string, or any falsy value
            time = item.get("best_lap").get("time", "") if item.get("best_lap") else ""

        race_result_json = {
            "race": race_id,
            "seasonGrid": season_grid_map[item["rider"]["number"]],
            "position": pos,
            "points": item.get("points", 0),
            "laps": item.get("total_laps", 0),
            "time": time,
            "dnf" : item.get("status") != "INSTND",

        }
        rider_id = item["rider"]["id"]
        print(f"Processing rider_id: {rider_id} at position: {pos}")
        if item["rider"]["id"] == fastest_lap_rider_id:
            race_result_json["fastestLap"] = True
            race_result_json["fastestLapTime"] = fastest_lap_record.get("bestLap", {}).get("time", "")
            race_result_json["fastestLapNo"] = fastest_lap_record.get("bestLap", {}).get("number", 0)

        if race_type == "QNR1" and index > 1 :
            race_result_json["finalPos"] = index + 11

        print(f"race_result: {race_result_json}")
        if driver_number_to_id_map:
            row_id = driver_number_to_id_map[item["rider"]["number"]]
            print(f" row id: {row_id} for {item["rider"]["number"]}")
            update_race_result(is_f1_feed=False, json_str=json.dumps(race_result_json), row_id=row_id)
        else:
            create_race_result(is_f1_feed=False, json_str=json.dumps(race_result_json))

    print("######################")
    print(f"update stats")
    update_config_for_race_result(is_f1_feed=False, gp_id=gp_id)
    print("######################")
    print(f"sending race complete notification")
    send_race_complete_notification(is_f1=False, race_type=race_type, grand_prix=grand_prix)


if __name__ == "__main__":
    process()