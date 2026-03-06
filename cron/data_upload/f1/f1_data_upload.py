from cron.data_upload.f1.f1_data_upload_utils import fetch_race_results
from cron.data_upload.f1.f1_utils import qualifying_1, qualifying_2, sprint_qualifying_1, sprint_qualifying_2, \
    race_type_to_url_map
from cron.notifiaction.notification_utils import send_race_complete_notification
from cron.stats_calc.f1.f1_stats_update import process_update_f1_stats
from cron.strapi_api.apis import get_latest_past_race, get_race_results_for_race_event, get_season_grid_map, \
    create_race_result, update_config_for_race_result
import json
from loguru import logger

from cron.utils import f1_graphql_token


def process():
    logger.info("fetching the schedule")
    logger.info(f"Using Token 1: {f1_graphql_token[:5]}*****")
    json_data = get_latest_past_race(is_f1_feed=True)

    races = json_data["data"]["races"]["data"]

    race_id = races[0]["id"] if len(races) > 0 else None
    q2_id   = races[1]["id"] if len(races) > 1 else None
    q1_id   = races[2]["id"] if len(races) > 2 else None

    if race_id:
        race_type = json_data["data"]["races"]["data"][0]["attributes"]["type"]
        grand_prix = json_data["data"]["races"]["data"][0]["attributes"]["grandPrix"]["data"]
        logger.info(f"race_id: {race_id} --- race_type: {race_type}")
        strapi_races = get_race_results_for_race_event(is_f1_feed=True, race_id=race_id)
        race_result_count = len(strapi_races['data']['raceResults']['data'])
        logger.info(f"race_result_count from strapi: {race_result_count}")

        gp_id = grand_prix.get("id")
        logger.info(f"gp_id: {gp_id}")

        if race_result_count == 0:
            year = json_data["data"]["races"]["data"][0]["attributes"]["grandPrix"]["data"]["attributes"]["season"]["data"]["attributes"]["year"]
            site_event_id = json_data["data"]["races"]["data"][0]["attributes"]["grandPrix"]["data"]["attributes"]["siteEventId"]
            event_name = json_data["data"]["races"]["data"][0]["attributes"]["grandPrix"]["data"]["attributes"]["shortName"]
            session_type = json_data["data"]["races"]["data"][0]["attributes"]["type"]

            logger.info(f"year: {year}, event_name: {event_name}, session_type: {session_type} site_event_id: {site_event_id}")

            if race_type not in (qualifying_1, qualifying_2, sprint_qualifying_1, sprint_qualifying_2) :
                logger.info("proceeding ahead to fetch the data")
                race_identifier = race_type_to_url_map[race_type]
                logger.info(f"race_identifier: {race_identifier}")
                f1_url = site_event_id + race_identifier
                logger.info(f"f1_url: {f1_url}")
                season_grid_map = get_season_grid_map(is_f1_feed=True, season=year)
                rows = fetch_race_results(f1_url, season_grid_map, race_id, race_type, year, q2_id, q1_id)
                if len(rows) < 10:
                    logger.warning(f"Insufficient race results fetched for URL: {f1_url}. Expected at least 10, got {len(rows)}.")
                    return
                for row in rows:
                    create_race_result(is_f1_feed=True, json_str=json.dumps(row))

                update_config_for_race_result(is_f1_feed=True, gp_id=gp_id)
                # update stats after data upload
                logger.info("######################")
                logger.info(f"updating stats for year: {year}")
                process_update_f1_stats(season_year=year)
                # send notification
                logger.info("######################")
                logger.info(f"sending race complete notification for year: {year}")
                send_race_complete_notification(is_f1=True, race_type=race_type, grand_prix=grand_prix)

        else:
            logger.info("race results already present in strapi. no action needed.")
    else :
        logger.warning("No race id found")


if __name__ == "__main__":
    process()