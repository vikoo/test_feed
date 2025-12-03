from typing import Any

import requests

from cron.moto_gp.moto_gp_utils import to_utc

end_point = "https://api.pulselive.motogp.com/motogp"

def fetch_schedule(year: str) -> list[Any]:
    schedule_end_point = end_point + "/v1/events?seasonYear=" + year
    response = requests.get(schedule_end_point, timeout=30)
    response.raise_for_status()

    events = response.json()
    gp_events = []

    for event in events:
        # Filter only GP events
        if event.get("kind") != "GP":
            continue

        circuit = event.get("circuit", {})
        track = circuit.get("track", {})
        length_units = track.get("lenght_units", {})

        gp_data = {
            "id": event.get("id"),
            "sequence": event.get("sequence"),
            "date_start_utc": to_utc(event.get("date_start")),
            "date_end_utc": to_utc(event.get("date_end")),
            "name": event.get("name"),
            "shortname": event.get("shortname"),

            # Circuit fields
            "circuit_country": circuit.get("country"),
            "circuit_name": circuit.get("name"),

            # Track length
            "track_length_km": length_units.get("kiloMeters"),

            # Broadcasts (processed also with UTC conversion)
            "broadcasts": []
        }

        # Process broadcasts
        for b in event.get("broadcasts", []):
            broadcast_data = {
                "id": b.get("id"),
                "shortname": b.get("shortname"),
                "name": b.get("name"),
                "kind": b.get("kind"),
                "type": b.get("type"),
                "status": b.get("status"),
                "date_start_utc": to_utc(b.get("date_start")),
                "date_end_utc": to_utc(b.get("date_end")),
                "category": b.get("category", {}).get("name"),
            }
            gp_data["broadcasts"].append(broadcast_data)

        gp_events.append(gp_data)

    # Print result (or save it)
    for event in gp_events:
        print(event)

    return gp_events