from cron.data_upload.f1.f1_data_upload_utils import fetch_race_results
from cron.data_upload.f1.f1_utils import qualifying_1, qualifying_2, sprint_qualifying_1, sprint_qualifying_2, \
    race_type_to_url_map
from cron.stats_calc.f1.f1_stats_update import process_update_stats
from cron.strapi_api.apis import get_latest_past_race, get_race_results_for_race_event, get_season_grid_map, \
    create_race_result
import json


def process():
    print("fetching the schedule")
    json_data = get_latest_past_race(is_f1_feed=True)

    races = json_data["data"]["races"]["data"]

    race_id = races[0]["id"] if len(races) > 0 else None
    q2_id   = races[1]["id"] if len(races) > 1 else None
    q1_id   = races[2]["id"] if len(races) > 2 else None

    if race_id:
        race_type = json_data["data"]["races"]["data"][0]["attributes"]["type"]

        print(f"race_id: {race_id} --- race_type: {race_type}")
        strapi_races = get_race_results_for_race_event(is_f1_feed=True, race_id=race_id)
        race_result_count = len(strapi_races['data']['raceResults']['data'])
        print(f"race_result_count from strapi: {race_result_count}")

        if race_result_count == 0:
            year = json_data["data"]["races"]["data"][0]["attributes"]["grandPrix"]["data"]["attributes"]["season"]["data"]["attributes"]["year"]
            site_event_id = json_data["data"]["races"]["data"][0]["attributes"]["grandPrix"]["data"]["attributes"]["siteEventId"]
            event_name = json_data["data"]["races"]["data"][0]["attributes"]["grandPrix"]["data"]["attributes"]["shortName"]
            session_type = json_data["data"]["races"]["data"][0]["attributes"]["type"]

            print(f"year: {year}, event_name: {event_name}, session_type: {session_type} site_event_id: {site_event_id}")

            if race_type not in (qualifying_1, qualifying_2, sprint_qualifying_1, sprint_qualifying_2) :
                print(f"proceeding ahead to fetch the data)")
                race_identifier = race_type_to_url_map[race_type]
                print(f"race_identifier: {race_identifier}")
                f1_url = site_event_id + race_identifier
                print(f"f1_url: {f1_url}")
                season_grid_map = get_season_grid_map(is_f1_feed=True, season=year)
                rows = fetch_race_results(f1_url, season_grid_map, race_id, race_type, year, q2_id, q1_id)
                for row in rows:
                    create_race_result(is_f1_feed=True, json_str=json.dumps(row))

                # update stats after data upload
                process_update_stats(season_year=year)

        else:
            print(f"race results already present in strapi. no action needed.")
    else :
        print(f"No race id found")


if __name__ == "__main__":
    process()