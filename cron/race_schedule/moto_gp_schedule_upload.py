import argparse
from datetime import datetime, timezone

from cron.moto_gp.moto_gp_api import fetch_schedule
from cron.race_schedule.schedule_utils import valid_year

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download MotoGP GP events by season year")
    parser.add_argument(
        "--year",
        type=valid_year,
        default=datetime.now(timezone.utc).year,
        help="Season year (e.g. 2024)"
    )
    args = parser.parse_args()

    print(f"------------- updating schedule for year {args.year}------------------")
    fetch_schedule(str(args.year))
