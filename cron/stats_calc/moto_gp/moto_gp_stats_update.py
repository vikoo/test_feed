import argparse
from datetime import datetime, timezone

from loguru import logger

from cron.race_schedule.moto_gp.moto_gp_schedule_utils import valid_year
from cron.stats_calc.moto_gp.moto_gp_stats_update_utils import update_moto_gp_stats
from cron.strapi_api.apis import fetch_all_race_results, fetch_driver_team_standings_for_season, update_config_for_stats


def process_update_moto_gp_stats(season_year: str):
    logger.info("Processing MotoGP stats update...")
    race_results = fetch_all_race_results(is_f1_feed=False, season=season_year)
    logger.info(f"Fetched {len(race_results)}")
    driver_standings, team_standings = fetch_driver_team_standings_for_season(is_f1_feed=False, season=season_year)
    update_moto_gp_stats(season_year, race_results, driver_standings, team_standings)
    update_config_for_stats(is_f1_feed=False, season_year=season_year)

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