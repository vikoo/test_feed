import argparse
from datetime import datetime, timezone

from cron.moto_gp.moto_gp_api import fetch_moto_gp_schedule_map_with_short_name
from cron.race_schedule.moto_gp.moto_gp_schedule_utils import valid_year, get_tracks_map, handle_season_creation, process_strapi_gp_with_moto_gp
from cron.strapi_api.apis import get_grand_prix_races_for_year


def process(schedule_year: str):
    print(f"------------- updating schedule for year {schedule_year}------------------")
    # fetching moto gp schedule


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download F1 GP events by season year")
    parser.add_argument(
        "--year",
        type=valid_year,
        default=datetime.now(timezone.utc).year,
        help="Season year (e.g. 2024)"
    )
    args = parser.parse_args()
    year = str(args.year)
    process(year)


