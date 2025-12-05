import argparse
from datetime import datetime, timezone

from cron.moto_gp.moto_gp_api import fetch_moto_gp_schedule_map_with_short_name
from cron.race_schedule.moto_gp_schedule_utils import valid_year, contains_season, create_season_entry_and_update_config, \
    get_tracks_map, handle_season_creation, process_strapi_gp_with_moto_gp
from cron.strapi_api.apis import get_grand_prix_races_for_year


def process(schedule_year: str):
    print(f"------------- updating schedule for year {schedule_year}------------------")
    # fetching moto gp schedule
    moto_gp_schedule_map_with_short_name = fetch_moto_gp_schedule_map_with_short_name(schedule_year)
    # print(f"schedule: {moto_gp_schedule_map_with_short_name}")

    # fetching season and grandprix for given season
    found, season_id = handle_season_creation(is_f1_feed=False, target_year=schedule_year)
    if found:
        grand_prixes, races = get_grand_prix_races_for_year(is_f1_feed=False, year=schedule_year)
        print("Grand Prixes:", grand_prixes)
        print("Races:", races)
        track_map = get_tracks_map(is_f1_feed=False)
        print("track_map:", track_map)
        process_strapi_gp_with_moto_gp(moto_gp_schedule_map_with_short_name, grand_prixes, races, track_map, season_id, schedule_year)
    else :
        print(f"unable to create or find season")

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


