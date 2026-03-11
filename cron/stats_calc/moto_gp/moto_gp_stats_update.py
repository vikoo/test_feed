import argparse
from datetime import datetime, timezone

from loguru import logger

from cron.moto_gp.moto_gp_api import fetch_season, fetch_constructor_standings
from cron.race_schedule.moto_gp.moto_gp_schedule_utils import valid_year, contains_season
from cron.stats_calc.moto_gp.moto_gp_stats_update_utils import update_moto_gp_stats
from cron.strapi_api.apis import fetch_all_race_results, fetch_driver_team_standings_for_season, \
    update_config_for_stats, fetch_constructor_standings_for_season_moto_gp, \
    update_constructor_standings_for_season_moto_gp, create_constructor_standings_for_season_moto_gp


def process_update_moto_gp_stats(season_year: str):
    logger.info("Processing MotoGP stats update...")
    race_results = fetch_all_race_results(is_f1_feed=False, season=season_year)
    logger.info(f"Fetched {len(race_results)}")
    driver_standings, team_standings = fetch_driver_team_standings_for_season(is_f1_feed=False, season=season_year)
    update_moto_gp_stats(season_year, race_results, driver_standings, team_standings)
    process_constructor_stats_update(season_year)
    update_config_for_stats(is_f1_feed=False, season_year=season_year)

def process_constructor_stats_update(season_year: str):
    logger.info(f"Processing MotoGP constructor stats update... for season: {season_year}")
    season_uuid = fetch_season(year=season_year)
    logger.info(f"season_uuid: {season_uuid}")
    ctr_standings = fetch_constructor_standings(season_uuid)
    constructor_list = ctr_standings.get("classification", {}).get("constructor", [])
    ctr_standings_dict = {
        entry["constructor"]["name"]: {
            "position": entry["position"],
            "points": entry["points"],
        }
        for entry in constructor_list
    }
    logger.info(f"Constructor standings from moto gp: {ctr_standings_dict}")
    update_constructor_stats_in_strapi(season_year, ctr_standings_dict)

def update_constructor_stats_in_strapi(season_year: str, ctr_standings_dict: dict):
    logger.info(f"fetch constructor stats from strapi for the season: {season_year}")
    strapi_constructor_stats = fetch_constructor_standings_for_season_moto_gp(is_f1_feed=False, season=season_year)
    if not strapi_constructor_stats:
        logger.info("No constructor stats found in Strapi")
        found, season_id = contains_season(is_f1_feed=False, target_year=season_year)
        if found:
            logger.info(f"Season found in Strapi with id: {season_id}. Creating constructor stats entries.")
            for constructor_name, stats in ctr_standings_dict.items():
                json = {
                    "position": stats["position"],
                    "points": stats["points"],
                    "name": constructor_name,
                    "season": season_id
                }
                create_constructor_standings_for_season_moto_gp(is_f1_feed=False, json_standings=json)
    else:
        logger.info(f"Found {len(strapi_constructor_stats)} constructor stats in Strapi")
        for stat in strapi_constructor_stats:
            stat_id = stat["id"]
            constructor_name = stat["attributes"]["name"]
            logger.info(f"constructor_name: {constructor_name} --- id: {stat_id}")

            json = {
                "position": ctr_standings_dict[constructor_name]["position"],
                "points": ctr_standings_dict[constructor_name]["points"],
                "name": constructor_name
            }
            update_constructor_standings_for_season_moto_gp(is_f1_feed=False, row_id=stat_id,json_standings=json)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download MotoGP GP events by season year")
    parser.add_argument(
        "--year",
        type=valid_year,
        default=datetime.now(timezone.utc).year,
        help="Season year (e.g. 2024)"
    )
    args = parser.parse_args()
    year = str(args.year)
    process_update_moto_gp_stats(season_year=year)