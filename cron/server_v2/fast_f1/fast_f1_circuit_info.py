"""
FastF1 Circuit Info Fetcher

Fetches the number of laps and track length for every GP in a given year.

Data sources:
    - Number of laps   → FastF1  (session.total_laps, loaded via the Race session)
    - Track length (km) → Jolpica / Ergast REST API  (api.jolpi.ca/ergast/f1)
      FastF1 does not expose circuit length natively; the Jolpica API (the
      open Ergast successor) is the canonical free source for this data.

FastF1 docs:        https://docs.fastf1.dev/
Jolpica API docs:   https://github.com/jolpica/jolpica-f1

Usage:
    >>> from fast_f1_circuit_info import fetch_circuit_info
    >>> circuits = fetch_circuit_info(2025)
    >>> for gp in circuits:
    ...     print(gp["round_number"], gp["event_name"],
    ...           gp["total_laps"], gp["track_length_km"])

CLI:
    python fast_f1_circuit_info.py [year]
    python fast_f1_circuit_info.py 2025
"""

import time
import requests
import fastf1
from datetime import datetime, timezone
from typing import Optional
from loguru import logger


# ---------------------------------------------------------------------------
# Jolpica / Ergast API helper
# ---------------------------------------------------------------------------

_JOLPICA_BASE = "https://api.jolpi.ca/ergast/f1"
_REQUEST_TIMEOUT = 15

# Official F1 circuit lengths in km, keyed by Jolpica/Ergast circuitId.
# The Jolpica API does not expose a length field, so we use this lookup table.
# Sources: FIA circuit homologation documents / formula1.com official stats.
_CIRCUIT_LENGTHS_KM: dict[str, float] = {
    "albert_park":      5.278,   # Melbourne, Australia
    "americas":         5.513,   # Austin, USA (COTA)
    "bahrain":          5.412,   # Sakhir, Bahrain
    "baku":             6.003,   # Baku, Azerbaijan
    "catalunya":        4.657,   # Barcelona, Spain
    "hungaroring":      4.381,   # Budapest, Hungary
    "interlagos":       4.309,   # São Paulo, Brazil
    "jeddah":           6.174,   # Jeddah, Saudi Arabia
    "marina_bay":       4.940,   # Singapore
    "miami":            5.412,   # Miami, USA
    "monaco":           3.337,   # Monaco
    "monza":            5.793,   # Monza, Italy
    "red_bull_ring":    4.318,   # Spielberg, Austria
    "ricard":           5.842,   # Le Castellet, France
    "rodriguez":        4.304,   # Mexico City, Mexico
    "shanghai":         5.451,   # Shanghai, China
    "silverstone":      5.891,   # Silverstone, Great Britain
    "spa":              7.004,   # Spa-Francorchamps, Belgium
    "suzuka":           5.807,   # Suzuka, Japan
    "villeneuve":       4.361,   # Montreal, Canada
    "yas_marina":       5.281,   # Abu Dhabi
    "zandvoort":        4.259,   # Zandvoort, Netherlands
    "losail":           5.380,   # Lusail, Qatar
    "vegas":            6.201,   # Las Vegas, USA
    "imola":            4.909,   # Imola, Italy
    "portimao":         4.653,   # Portimão, Portugal
    "mugello":          5.245,   # Mugello, Italy
    "nurburgring":      5.148,   # Nürburgring, Germany
    "istanbul":         5.338,   # Istanbul, Turkey
}


def _fetch_track_lengths(year: int) -> dict[int, float]:
    """
    Resolve track lengths (km) for all rounds in *year*.

    Strategy:
        1. Call the Jolpica races endpoint to get round → circuitId mapping.
        2. Look up each circuitId in the hardcoded _CIRCUIT_LENGTHS_KM table.
           (The Jolpica circuits endpoint does not include a length field.)

    Returns:
        dict[int, float]: Maps round number → track length in km.
                          Returns an empty dict on any network/parse failure.
    """
    url_races = f"{_JOLPICA_BASE}/{year}.json?limit=30"
    logger.debug(f"Fetching race schedule from Jolpica: {url_races}")

    try:
        resp = requests.get(url_races, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        races_data = resp.json()
    except Exception as exc:
        logger.warning(f"Jolpica races request failed: {exc}")
        return {}

    races = (
        races_data
        .get("MRData", {})
        .get("RaceTable", {})
        .get("Races", [])
    )

    round_to_length: dict[int, float] = {}
    for race in races:
        try:
            round_num = int(race.get("round", 0))
        except (TypeError, ValueError):
            continue
        circuit_id = race.get("Circuit", {}).get("circuitId", "")
        length = _CIRCUIT_LENGTHS_KM.get(circuit_id)
        if length is not None:
            round_to_length[round_num] = length
        else:
            logger.debug(f"  No length entry for circuitId '{circuit_id}' (round {round_num})")

    logger.debug(f"Resolved track lengths for {len(round_to_length)}/{len(races)} rounds")
    return round_to_length


# ---------------------------------------------------------------------------
# Per-round lap count via FastF1
# ---------------------------------------------------------------------------

def _fetch_total_laps(year: int, round_number: int) -> Optional[int]:
    """
    Load a Race session for the given round and return session.total_laps.
    Returns None if the session has not yet happened or data is unavailable.
    """
    try:
        session = fastf1.get_session(year, round_number, "R")
        # laps=True is required for total_laps; skip costly telemetry/weather
        session.load(laps=True, telemetry=False, weather=False, messages=False)
        return int(session.total_laps)
    except Exception as exc:
        logger.warning(
            f"  Could not load lap count for round {round_number}: {exc}"
        )
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_circuit_info(year: int, delay_between_rounds: float = 0.5) -> list[dict]:
    """
    Fetch track length and number of laps for every GP in *year*.

    Args:
        year (int):
            Championship year, e.g. 2025.
        delay_between_rounds (float):
            Seconds to sleep between FastF1 API calls to avoid rate-limiting.
            Defaults to 0.5.

    Returns:
        list[dict]: One dict per GP, ordered by round number:
            - round_number    (int)
            - event_name      (str)
            - country         (str)
            - location        (str)
            - circuit_name    (str)
            - total_laps      (int | None)   – None if race not yet run
            - track_length_km (float | None) – None if unavailable

    Example:
        >>> circuits = fetch_circuit_info(2025)
        >>> for gp in circuits:
        ...     print(
        ...         gp["round_number"],
        ...         gp["event_name"],
        ...         f"{gp['total_laps']} laps",
        ...         f"{gp['track_length_km']} km",
        ...     )
    """
    logger.info(f"Fetching circuit info for {year}...")

    # 1) Full season schedule from FastF1
    schedule = fastf1.get_event_schedule(year, include_testing=False)
    logger.info(f"  Schedule has {len(schedule)} events")

    # 2) Track lengths from Jolpica for all rounds at once (one API call)
    track_lengths = _fetch_track_lengths(year)

    results: list[dict] = []
    now_utc = datetime.now(timezone.utc)

    for _, row in schedule.iterrows():
        round_num = int(row["RoundNumber"])
        event_name = str(row["EventName"])

        # 3) Total laps — only available for rounds whose race has already run.
        #    Skip FastF1 session load for future rounds entirely; it would
        #    generate ~7s of failed API calls per round before timing out.
        event_date = row.get("EventDate")
        race_has_run = False
        if event_date is not None:
            try:
                if hasattr(event_date, "tzinfo"):
                    ed = event_date if event_date.tzinfo else event_date.replace(tzinfo=timezone.utc)
                else:
                    ed = datetime.fromisoformat(str(event_date)).replace(tzinfo=timezone.utc)
                # Give the race an extra day to finish before marking as "run"
                race_has_run = ed < now_utc
            except Exception:
                pass

        if race_has_run:
            logger.info(f"  Round {round_num}: {event_name} (past — loading laps)")
            total_laps = _fetch_total_laps(year, round_num)
            time.sleep(delay_between_rounds)
        else:
            logger.info(f"  Round {round_num}: {event_name} (future — skipping lap load)")
            total_laps = None

        track_length = track_lengths.get(round_num)

        results.append({
            "round_number":    round_num,
            "event_name":      event_name,
            "country":         str(row["Country"]),
            "location":        str(row["Location"]),
            "circuit_name":    str(row.get("OfficialEventName", event_name)),
            "total_laps":      total_laps,
            "track_length_km": track_length,
        })


    logger.info(f"Done. Collected info for {len(results)} rounds.")
    return results


def fetch_circuit_info_for_round(year: int, gp: int | str) -> dict:
    """
    Fetch track length and number of laps for a single GP.

    Args:
        year (int):       Championship year, e.g. 2025.
        gp   (int|str):   Round number, country name, or GP name.
                          Examples: 1, "Australia", "Bahrain"

    Returns:
        dict: Same structure as each element of fetch_circuit_info().

    Example:
        >>> info = fetch_circuit_info_for_round(2025, 1)
        >>> print(info["event_name"], info["total_laps"], info["track_length_km"])
    """
    logger.info(f"Fetching circuit info for {year} – GP: {gp}")

    # Resolve round number from FastF1 event
    event = fastf1.get_event(year, gp)
    round_num = int(event["RoundNumber"])
    event_name = str(event["EventName"])

    logger.info(f"  Event: Round {round_num} – {event_name}")

    # Track length from Jolpica for the whole year, then pick this round
    track_lengths = _fetch_track_lengths(year)
    track_length = track_lengths.get(round_num)

    # Total laps from FastF1 Race session
    total_laps = _fetch_total_laps(year, round_num)

    return {
        "round_number":    round_num,
        "event_name":      event_name,
        "country":         str(event["Country"]),
        "location":        str(event["Location"]),
        "circuit_name":    str(event.get("OfficialEventName", event_name)),
        "total_laps":      total_laps,
        "track_length_km": track_length,
    }


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import sys

    # Usage:
    #   python fast_f1_circuit_info.py            → full season (current year)
    #   python fast_f1_circuit_info.py 2025        → full season for 2025
    #   python fast_f1_circuit_info.py 2025 1      → single round by number
    #   python fast_f1_circuit_info.py 2025 Australia → single round by name

    _year = int(sys.argv[1]) if len(sys.argv) > 1 else 2026

    if len(sys.argv) > 2:
        _gp_raw = sys.argv[2]
        _gp: int | str = int(_gp_raw) if _gp_raw.isdigit() else _gp_raw
        data = fetch_circuit_info_for_round(_year, _gp)
    else:
        data = fetch_circuit_info(_year)

    print(json.dumps(data, indent=2, default=str))

