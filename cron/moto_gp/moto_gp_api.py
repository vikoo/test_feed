from typing import Any

import requests

from cron.moto_gp.moto_gp_utils import to_utc

end_point = "https://api.pulselive.motogp.com/motogp"
TARGET_CATEGORY_ID = "93888447-8746-4161-882c-e08a1d48447e"
TARGET_CATEGORY_ID_FOR_RACE_RESULT = "e8c110ad-64aa-4e8e-8a86-f2f152f6a942"
event_category_map = {
    "FP1": "FP1",
    "FP2": "FP2",
    "PR": "PRACTICE",
    "SPR": "Sprint",
    "Q1": "QNR1",
    "Q2": "QNR2",
    "RAC": "Race",
}

race_session_map_from_strapi_to_moto_gp = {
    "FP1": "FP1",
    "PRACTICE": "PR",
    "FP2": "FP2",
    "QNR1": "Q1",
    "QNR2": "Q2",
    "Sprint": "SPR",
    "WUP": "WUP",
    "Race": "RAC"
}

def fetch_moto_gp_schedule_map_with_short_name(year: str):
    schedule_end_point = end_point + "/v1/events?seasonYear=" + year
    response = requests.get(schedule_end_point, timeout=30)
    response.raise_for_status()

    events = response.json()
    gp_events = {}

    for event in events:
        # Filter only GP events
        if event.get("kind") != "GP":
            continue

        circuit = event.get("circuit", {})
        event_categories = extract_race_category(event)

        short_name = event.get("shortname")
        gp_data = {
            "id": event.get("id"),
            "sequence": format(event.get("sequence"), "02"),
            "date_start_utc": to_utc(event.get("date_start")),
            "date_end_utc": to_utc(event.get("date_end")),
            "name": event.get("name"), # full name
            "additional_name": event.get("additional_name"), # append GP 23 for name
            "shortname": short_name,

            # Circuit fields
            "circuit_country": circuit.get("country"),
            "circuit_name": circuit.get("name"),

            # Track length
            "track_length_km": event_categories.get("length_km"),
            "track_num_laps": event_categories.get("num_laps"),
            "track_distance_km": event_categories.get("distance_km"),

            # Broadcasts (processed also with UTC conversion)
            "broadcasts": []
        }

        # Process broadcasts
        for b in event.get("broadcasts", []):
            category_id = b.get("category", {}).get("id")
            if category_id != TARGET_CATEGORY_ID:
                continue

            race_type = event_category_map.get(b.get("shortname"))
            if race_type:
                broadcast_data = {
                    "id": b.get("id"),
                    "name": b.get("name"),
                    "gp_short_name": event.get("shortname"),
                    "type": race_type, # this is type
                    "date_start_utc": to_utc(b.get("date_start")),
                    "date_end_utc": to_utc(b.get("date_end")),
                    "identifier": race_type + " - " + event.get("additional_name") + str(year)[-2:],
                }
                gp_data["broadcasts"].append(broadcast_data)

        gp_events[short_name] = gp_data

    # Print result (or save it)
    # for event in gp_events:
    #     print(event)

    return gp_events

def extract_race_category(event):
    for cat in event.get("event_categories", []):
        if cat.get("category_id") == TARGET_CATEGORY_ID:

            num_laps = cat.get("num_laps")
            distance_km = cat.get("distance", {}).get("kiloMeters")

            # Safety check
            if not num_laps or not distance_km:
                length = None
            else:
                length = round(distance_km / num_laps, 2)

            return {
                "num_laps": num_laps,
                "distance_km": distance_km,
                "length_km": length
            }

    return None

def fetch_season(year: str)-> str:
    season_end_point = end_point + "/v1/results/seasons"
    response = requests.get(season_end_point, timeout=30)
    response.raise_for_status()

    seasons = response.json()
    for season in seasons:
        if str(season["year"]) == str(year):
            return season["id"]
    return None

def fetch_event(event_name: str, season_uuid: str)-> str:
    season_end_point = end_point + "/v1/results/events?seasonUuid=" + season_uuid
    response = requests.get(season_end_point, timeout=30)
    response.raise_for_status()

    events = response.json()
    for event in events:
        if event.get("short_name") == event_name:
            return event["id"]
    return None

def fetch_session(session_type: str, event_uuid: str)-> str:
    season_end_point = end_point + "/v1/results/sessions?categoryUuid=" + TARGET_CATEGORY_ID_FOR_RACE_RESULT + "&eventUuid=" + event_uuid
    response = requests.get(season_end_point, timeout=30)
    response.raise_for_status()

    sessions = response.json()
    motp_gp_session_type = race_session_map_from_strapi_to_moto_gp[session_type]
    for session in sessions:
        type_of_session = session.get("type")
        session_number = str(session.get("number"))
        #print(f"type_of_session: {type_of_session} --- session_number: {session_number}")
        if session_number != "None":
            type_of_session = type_of_session + session_number

        if type_of_session == motp_gp_session_type:
            return session["id"]
    return None


def fetch_race_results(session_uuid: str) :
    race_result_end_point = end_point + "/v2/results/classifications?session=" + session_uuid
    response = requests.get(race_result_end_point, timeout=30)
    response.raise_for_status()

    events = response.json()
    print(f"race results: {events}")
    return events