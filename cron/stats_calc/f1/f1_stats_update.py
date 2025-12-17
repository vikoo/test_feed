import argparse
from datetime import datetime, timezone

from cron.race_schedule.moto_gp.moto_gp_schedule_utils import valid_year
from cron.stats_calc.f1.f1_stats_update_utils import update_stats
from cron.strapi_api.apis import fetch_all_race_results, fetch_driver_team_standings_for_season


def process(season_year: str):
    print("Processing F1 stats update...")
    race_results = fetch_all_race_results(is_f1_feed=True, season=season_year)
    print(f"Fetched {len(race_results)}")
    driver_standings, team_standings = fetch_driver_team_standings_for_season(True, season_year)
    update_stats(season_year, race_results, driver_standings, team_standings)

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
    process(season_year = year)