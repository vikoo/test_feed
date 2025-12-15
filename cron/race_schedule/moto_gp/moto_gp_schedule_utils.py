import argparse
import json
from datetime import datetime, timezone

from cron.strapi_api.apis import create_season, get_config, get_seasons, update_config_for_season, get_tracks, \
    create_grand_prix, create_race, update_time_in_race, update_config_for_gp
from cron.utils import get_current_epoch


def valid_year(value):
    year = int(value)
    current_year = datetime.now(timezone.utc).year + 1   # allow next season

    if year < 1949 or year > current_year:
        raise argparse.ArgumentTypeError(
            f"Year must be between 1949 and {current_year}"
        )

    return year

def contains_season(is_f1_feed: bool, target_year: str):
    seasons = get_seasons(is_f1_feed)
    for season in seasons['data']['seasons']['data']:
        if season['attributes']['year'] == target_year:
            return True, season['id']
    return False, None

def create_season_entry_and_update_config(target_year: str):
    print(f"Creating a new entry in season table.")
    season_id = create_season(is_f1_feed=False, season_year=target_year)
    print(f"season id created: {season_id}")
    if season_id:
        print(f"updating config for new season.")
        config = get_config(is_f1_feed=False)
        team_standings_json_str = config.get("teamStandingsForSeasonJson")
        driver_standings_json_str = config.get("driverStandingsForSeasonJson")
        epoch = get_current_epoch()
        team_standings_json_str[target_year] = epoch
        driver_standings_json_str[target_year] = epoch
        update_config_for_season(is_f1_feed=False, team_standings_json_str=json.dumps(team_standings_json_str), driver_standings_json_str= json.dumps(driver_standings_json_str))
        return True, season_id
    return False, None

def handle_season_creation(is_f1_feed: bool, target_year: str):
    found, season_id = contains_season(is_f1_feed=is_f1_feed, target_year=target_year)
    if found:
        print(f"season exists with id:{season_id}. proceed ahead with grand prix and race fetch")
        return True, season_id
    else:
        print(f"season not found.")
        return create_season_entry_and_update_config(target_year)

def get_tracks_map(is_f1_feed: bool)-> dict[str, str]:
    tracks = get_tracks(is_f1_feed)
    track_map = {
        track['attributes']['name']: track['id']
        for track in tracks['data']['tracks']['data']
    }
    return track_map

def process_strapi_gp_with_moto_gp(moto_gp_schedule_map_with_short_name, grand_prixes, races, track_map, season_id, event_year):
    if not grand_prixes:
        print(f"NO grand prix found CREATING new entries for GP and races.")
        gp_short_name_to_id_map = {}
        for event in moto_gp_schedule_map_with_short_name.values():
            grand_prix_id = create_gp_entry(season_id, track_map, event, event_year)
            gp_short_name_to_id_map[event.get("shortname")] = grand_prix_id
            filtered_races_from_strapi_map = filter_races_by_grand_prix_as_dict(races, grand_prix_id)
            if not filtered_races_from_strapi_map:
                print(f" races are empty in strapi. create new entries.")
                create_race_entry(event.get("broadcasts"), grand_prix_id)
            else:
                update_race_entry(event.get("broadcasts"), filtered_races_from_strapi_map)
                print(f"races exists strapi. update date time in each entry.")
        # todo update the gp ids in config
        update_config_for_gp(is_f1_feed=False)

    else:
        print(f"grand prix and races found UPDATING entries for GP and races.")
        gp_short_name_already_uploaded = []
        for grand_prix in grand_prixes:
            grand_prix_id = grand_prix.get("id")
            filtered_races_from_strapi_map = filter_races_by_grand_prix_as_dict(races, grand_prix_id)
            grand_prix_short_name = grand_prix["attributes"]["shortName"]
            gp_short_name_already_uploaded.append(grand_prix_short_name)
            moto_gp_event = moto_gp_schedule_map_with_short_name[grand_prix_short_name]
            if not filtered_races_from_strapi_map:
                print(f" races are empty in strapi. create new entries.")
                create_race_entry(moto_gp_event.get("broadcasts"), grand_prix_id)
            else:
                update_race_entry(moto_gp_event.get("broadcasts"), filtered_races_from_strapi_map)
                print(f"races exists strapi. update date time in each entry.")

        print(f"checking if any grand prix is remaining to upload or not from moto gp schedule")
        for event_key in moto_gp_schedule_map_with_short_name.keys():
            if event_key in gp_short_name_already_uploaded:
                print(f"skipping GP already there")
                continue

            event = moto_gp_schedule_map_with_short_name[event_key]
            grand_prix_id = create_gp_entry(season_id, track_map, event, event_year)
            filtered_races_from_strapi_map = filter_races_by_grand_prix_as_dict(races, grand_prix_id)
            if not filtered_races_from_strapi_map:
                print(f" races are empty in strapi. create new entries.")
                create_race_entry(event.get("broadcasts"), grand_prix_id)
            else:
                update_race_entry(event.get("broadcasts"), filtered_races_from_strapi_map)
                print(f"races exists strapi. update date time in each entry.")

        # todo update the gp ids in config
        update_config_for_gp(is_f1_feed=False)

    return None

def create_gp_entry(season_id, track_map, event, event_year):
    grand_prix_json = {
        "season": season_id,
        "track": track_map.get(event.get("circuit_name")),
        "length": event.get("track_length_km"),
        "distance": event.get("track_distance_km"),
        "laps": event.get("track_num_laps"),
        "name": event.get("additional_name") + " GP " + str(event_year)[-2:],
        "startDate": event.get("date_start_utc"),
        "endDate": event.get("date_end_utc"),
        "type": "Normal",
        "fullName": event.get("name"),
        "round": event.get("sequence"),
        "shortName": event.get("shortname"),
        "siteEventId": event.get("id")
    }
    grand_prix_id = create_grand_prix(is_f1_feed=False, json_str=json.dumps(grand_prix_json))
    return grand_prix_id

def create_race_entry(moto_gp_races, grand_prix_id):
    for moto_gp_race in moto_gp_races:
        race_json = {
            "grandPrix": grand_prix_id,
            "startTime": moto_gp_race.get("date_start_utc"),
            "type":moto_gp_race.get("type"),
            "identifier": moto_gp_race.get("identifier"),
            "siteEventId": moto_gp_race.get("id")
        }
        create_race(is_f1_feed=False, json_str=json.dumps(race_json))

def update_race_entry(moto_gp_races, strapi_races_map):
    for moto_gp_race in moto_gp_races:
        strapi_race = strapi_races_map.get(moto_gp_race.get("type"))
        update_time_in_race(is_f1_feed=False, race_id=strapi_race["id"], start_time=moto_gp_race.get("date_start_utc"), site_event_id=moto_gp_race.get("id"))

def filter_races_by_grand_prix_as_dict(races: list, grand_prix_id: str) -> dict:
    return {
        race["attributes"]["type"]: race
        for race in races
        if race.get("attributes", {})
           .get("grandPrix", {})
           .get("data", {})
           .get("id") == grand_prix_id
    }
