import argparse
from datetime import datetime, timezone

from cron.moto_gp.moto_gp_api import fetch_schedule
from cron.race_schedule.schedule_utils import valid_year
from cron.strapi_api.apis import get_seasons, get_grand_prix_races_for_year, get_config


def process(schedule_year: str):
    print(f"------------- updating schedule for year {schedule_year}------------------")
    # moto_gp_schedule = fetch_schedule(schedule_year)
    # print(f"schedule: {moto_gp_schedule}")

    seasons = get_seasons(is_f1_feed=False)
    # grand_prix_races = get_grand_prix_races_for_year(is_f1_feed=False, year=schedule_year)
    # config = get_config(is_f1_feed=False)

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
    process(year)


