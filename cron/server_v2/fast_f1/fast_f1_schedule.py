"""
FastF1 Schedule Fetcher

Uses the fastf1 package to fetch the F1 Grand Prix schedule for a given year.
Each event includes all sessions (Practice 1/2/3, Qualifying, Sprint, Race)
with their UTC datetimes, plus circuit details (total_laps, track_length_km)
sourced from fast_f1_circuit_info.fetch_circuit_info().

Data sources:
    - Schedule / sessions  → FastF1 event schedule
    - Total laps           → fast_f1_circuit_info  (FastF1 Race session)
    - Track length (km)    → fast_f1_circuit_info  (Jolpica API + lookup table)

FastF1 docs:      https://docs.fastf1.dev/
Jolpica API docs: https://github.com/jolpica/jolpica-f1
"""

import sys
import os

# Allow running directly as a script from any working directory.
# fast_f1_schedule.py lives at test_feed/cron/server_v2/fast_f1/
# so 3 levels up lands on test_feed/ where the cron package lives.
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")))

import fastf1
from datetime import datetime
from typing import Optional
from loguru import logger

from cron.server_v2.fast_f1.fast_f1_circuit_info import fetch_circuit_info


def fetch_f1_schedule(year: int) -> list[dict]:
    """
    Fetch the full F1 Grand Prix schedule for a given year using FastF1,
    enriched with circuit details from fast_f1_circuit_info.fetch_circuit_info().

    Args:
        year (int): The championship year (e.g. 2025, 2026).

    Returns:
        list[dict]: A list of event dictionaries. Each dict contains:
            - round_number    (int)
            - event_name      (str)   – official event name
            - country         (str)
            - location        (str)   – circuit city
            - circuit_name    (str)   – full official event name
            - is_sprint       (bool)  – True if the weekend contains a Sprint
            - total_laps      (int | None)   – None if race not yet run
            - track_length_km (float | None) – None if unavailable
            - sessions        (list[dict])   – ordered list of sessions:
                - name        (str)   e.g. "Practice 1", "Race"
                - date_utc    (str)   ISO-8601 UTC datetime or None

    Raises:
        Exception: Propagates any FastF1 / network errors.

    Example:
        >>> schedule = fetch_f1_schedule(2025)
        >>> for event in schedule:
        ...     print(
        ...         event['round_number'], event['event_name'],
        ...         event['total_laps'], event['track_length_km']
        ...     )
    """
    logger.info(f"Fetching F1 schedule for {year}...")

    # ── 1. Circuit info (total_laps + track_length_km) for all rounds ────────
    #    fetch_circuit_info() calls FastF1 + Jolpica and returns one dict per
    #    round. Build a lookup keyed by round_number for O(1) access below.
    circuit_info_list = fetch_circuit_info(year)
    circuit_info: dict[int, dict] = {
        c["round_number"]: c for c in circuit_info_list
    }
    logger.info(f"Circuit info loaded for {len(circuit_info)} rounds")

    # ── 2. Full season event schedule from FastF1 ─────────────────────────────
    event_schedule = fastf1.get_event_schedule(year, include_testing=False)
    logger.info(f"Found {len(event_schedule)} events for {year}")

    # FastF1 schedule DataFrame session column names (name + UTC date)
    session_columns = [
        ("Session1", "Session1DateUtc"),
        ("Session2", "Session2DateUtc"),
        ("Session3", "Session3DateUtc"),
        ("Session4", "Session4DateUtc"),
        ("Session5", "Session5DateUtc"),
    ]

    schedule: list[dict] = []

    for _, row in event_schedule.iterrows():
        round_num = int(row["RoundNumber"])

        # ── Sessions ──────────────────────────────────────────────────────────
        sessions: list[dict] = []
        for name_col, date_col in session_columns:
            session_name: str = row.get(name_col, "")
            session_date = row.get(date_col)

            if not session_name:
                continue

            date_utc: Optional[str] = None
            if session_date is not None:
                try:
                    ts = session_date
                    if hasattr(ts, "tzinfo") and ts.tzinfo is not None:
                        date_utc = ts.isoformat()
                    else:
                        date_utc = ts.strftime("%Y-%m-%dT%H:%M:%S+00:00")
                except Exception as exc:
                    logger.warning(f"Could not parse date for {session_name}: {exc}")

            sessions.append({"name": session_name, "date_utc": date_utc})

        # ── Merge circuit info ────────────────────────────────────────────────
        ci = circuit_info.get(round_num, {})
        total_laps      = ci.get("total_laps")
        track_length_km = ci.get("track_length_km")

        event: dict = {
            "round_number":    round_num,
            "event_name":      str(row["EventName"]),
            "country":         str(row["Country"]),
            "location":        str(row["Location"]),
            "circuit_name":    str(row.get("OfficialEventName", row["EventName"])),
            "is_sprint":       bool(row.get("EventFormat", "") == "sprint"),
            "total_laps":      total_laps,
            "track_length_km": track_length_km,
            "sessions":        sessions,
        }

        schedule.append(event)
        logger.debug(
            f"  Round {round_num}: {event['event_name']} "
            f"({event['country']}) — {total_laps} laps, {track_length_km} km"
        )

    logger.info(f"Successfully built schedule with {len(schedule)} events")
    return schedule


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    # Usage: python fast_f1_schedule.py [year]
    _year = int(sys.argv[1]) if len(sys.argv) > 1 else datetime.now().year

    data = fetch_f1_schedule(_year)
    print(json.dumps(data, indent=2, default=str))
