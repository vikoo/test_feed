from cron.moto_gp.moto_gp_api import fetch_season, fetch_event, fetch_session, fetch_race_results
from cron.strapi_api.apis import get_latest_past_race, get_race_results_for_race_event, get_season_grid_map, \
    create_race_result
import json


def process():
    print("fetching the schedule")
    json_data = get_latest_past_race(is_f1_feed=False)

    # Extract the year

    race_id = json_data["data"]["races"]["data"][0]["id"]
    race_type = json_data["data"]["races"]["data"][0]["attributes"]["type"]
    print(f"race_id: {race_id} --- race_type: {race_type}")
    strapi_races = get_race_results_for_race_event(is_f1_feed=False, race_id=race_id)
    race_result_count = len(strapi_races['data']['raceResults']['data'])
    print(f"race_result_count from strapi: {race_result_count}")

    if race_result_count == 0:
        year = json_data["data"]["races"]["data"][0]["attributes"]["grandPrix"]["data"]["attributes"]["season"]["data"]["attributes"]["year"]
        event_name = json_data["data"]["races"]["data"][0]["attributes"]["grandPrix"]["data"]["attributes"]["shortName"]
        session_type = json_data["data"]["races"]["data"][0]["attributes"]["type"]
        print(f"year: {year}, event_name: {event_name}, session_type: {session_type}")
        season_uuid = fetch_season(year)
        print(f"season_uuid: {season_uuid}")
        event_uuid= fetch_event(event_name=event_name,season_uuid=season_uuid)
        print(f"event_uuid: {event_uuid}")
        session_uuid = fetch_session(session_type=session_type, event_uuid=event_uuid)
        print(f"session_uuid: {session_uuid}")
        moto_gp_race_results = fetch_race_results(session_uuid)
        season_grid_map = get_season_grid_map(is_f1_feed=False, season=year)
        upload_moto_gp_race_results(moto_gp_race_results, season_grid_map, race_id, race_type)

    else:
        print("Race results already exist in Strapi. No need to fetch from MotoGP API.")

def upload_moto_gp_race_results(moto_gp_race_results, season_grid_map, race_id, race_type):
    classification = moto_gp_race_results.get("classification", [])
    records = moto_gp_race_results.get("records", [])

    fastest_lap_rider_id = None
    fastest_lap_record = None

    for record in records:
        if record.get("type") == "fastestLap":
            fastest_lap_rider_id = record.get("rider", {}).get("id")
            fastest_lap_record = record
            print(f"fastest_lap_rider_id: {fastest_lap_rider_id}")
            break

    for index, item in enumerate(classification):
        pos = item.get("position")
        pos = pos if pos is not None else (index + 1)
        race_result_json = {
            "race": race_id,
            "seasonGrid": season_grid_map[item["rider"]["number"]],
            "position": pos,
            "points": item.get("points", 0),
            "laps": item.get("totalLaps", 0),
            "time": item.get("time", ""),
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

        create_race_result(is_f1_feed=False, json_str=json.dumps(race_result_json))


if __name__ == "__main__":
    process()