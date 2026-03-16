"""
FastF1 Session Results Fetcher

Uses the fastf1 package to fetch results for a specific F1 session
(Race, Qualifying, Practice 1/2/3, Sprint, Sprint Qualifying) for a given
year and Grand Prix.

Supported session identifiers:
    'R'   – Race
    'Q'   – Qualifying
    'S'   – Sprint
    'SQ'  – Sprint Qualifying
    'FP1' – Practice 1
    'FP2' – Practice 2
    'FP3' – Practice 3

FastF1 docs: https://docs.fastf1.dev/
"""

import fastf1
import pandas as pd
from typing import Optional
from loguru import logger

# Valid session identifiers accepted by FastF1
SESSION_IDENTIFIERS = {
    "R":   "Race",
    "Q":   "Qualifying",
    "S":   "Sprint",
    "SQ":  "Sprint Qualifying",
    "FP1": "Practice 1",
    "FP2": "Practice 2",
    "FP3": "Practice 3",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_str(value) -> Optional[str]:
    """Return a clean string or None for NaN / NaT / None values."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return str(value)


def _safe_float(value) -> Optional[float]:
    """Return a float or None for NaN / None values."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _timedelta_to_seconds(td) -> Optional[float]:
    """Convert a pandas Timedelta to total seconds, or None."""
    if td is None:
        return None
    try:
        if pd.isna(td):
            return None
        return td.total_seconds()
    except (TypeError, ValueError):
        return None


def _parse_race_results(results: pd.DataFrame) -> list[dict]:
    """Parse Race / Sprint results into a list of driver dicts."""
    drivers = []
    for _, row in results.iterrows():
        drivers.append({
            "position":          _safe_str(row.get("Position")),
            "driver_number":     _safe_str(row.get("DriverNumber")),
            "driver_code":       _safe_str(row.get("Abbreviation")),
            "full_name":         _safe_str(row.get("FullName")),
            "first_name":        _safe_str(row.get("FirstName")),
            "last_name":         _safe_str(row.get("LastName")),
            "team":              _safe_str(row.get("TeamName")),
            "grid_position":     _safe_str(row.get("GridPosition")),
            "status":            _safe_str(row.get("Status")),      # e.g. "Finished", "+1 Lap"
            "points":            _safe_float(row.get("Points")),
            "fastest_lap":       _safe_str(row.get("FastestLap")),   # bool → str
            "fastest_lap_time":  _timedelta_to_seconds(row.get("FastestLapTime")),
            "fastest_lap_speed": _safe_float(row.get("FastestLapSpeed")),
            "time_seconds":      _timedelta_to_seconds(row.get("Time")),
        })
    return drivers


def _parse_qualifying_results(results: pd.DataFrame) -> list[dict]:
    """Parse Qualifying / Sprint Qualifying results into a list of driver dicts."""
    drivers = []
    for _, row in results.iterrows():
        drivers.append({
            "position":      _safe_str(row.get("Position")),
            "driver_number": _safe_str(row.get("DriverNumber")),
            "driver_code":   _safe_str(row.get("Abbreviation")),
            "full_name":     _safe_str(row.get("FullName")),
            "first_name":    _safe_str(row.get("FirstName")),
            "last_name":     _safe_str(row.get("LastName")),
            "team":          _safe_str(row.get("TeamName")),
            "q1_seconds":    _timedelta_to_seconds(row.get("Q1")),
            "q2_seconds":    _timedelta_to_seconds(row.get("Q2")),
            "q3_seconds":    _timedelta_to_seconds(row.get("Q3")),
        })
    return drivers


def _parse_practice_results(results: pd.DataFrame) -> list[dict]:
    """Parse Practice session results into a list of driver dicts."""
    drivers = []
    for _, row in results.iterrows():
        drivers.append({
            "position":      _safe_str(row.get("Position")),
            "driver_number": _safe_str(row.get("DriverNumber")),
            "driver_code":   _safe_str(row.get("Abbreviation")),
            "full_name":     _safe_str(row.get("FullName")),
            "first_name":    _safe_str(row.get("FirstName")),
            "last_name":     _safe_str(row.get("LastName")),
            "team":          _safe_str(row.get("TeamName")),
            "best_lap_time_seconds": _timedelta_to_seconds(row.get("Time")),
            "laps":          _safe_str(row.get("NumberOfLaps")),
        })
    return drivers


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_session_results(
    year: int,
    gp: str | int,
    session: str = "R",
) -> dict:
    """
    Fetch results for a specific F1 session using FastF1.

    Args:
        year    (int):       Championship year, e.g. 2026.
        gp      (str|int):   Grand Prix name, country name, or round number (int).
                             Examples: "Australia", "Bahrain", "Monza", 1, 5
        session (str):       Session identifier. One of:
                               'R'   – Race (default)
                               'Q'   – Qualifying
                               'S'   – Sprint
                               'SQ'  – Sprint Qualifying
                               'FP1' – Practice 1
                               'FP2' – Practice 2
                               'FP3' – Practice 3

    Returns:
        dict: A results dictionary containing:
            - year           (int)
            - gp             (str)   – official event name
            - session        (str)   – session identifier
            - session_name   (str)   – human-readable session name
            - round_number   (int)
            - country        (str)
            - location       (str)
            - circuit        (str)
            - date_utc       (str)   – ISO-8601 session date in UTC
            - total_drivers  (int)
            - results        (list[dict]) – per-driver results

    Raises:
        ValueError: If an unsupported session identifier is provided.
        Exception:  Propagates FastF1 / network errors.

    Example:
        >>> results = fetch_session_results(2026, "Australia", "R")
        >>> for driver in results['results']:
        ...     print(driver['position'], driver['full_name'])
    """
    session = session.upper()
    if session not in SESSION_IDENTIFIERS:
        raise ValueError(
            f"Unsupported session '{session}'. "
            f"Choose from: {', '.join(SESSION_IDENTIFIERS)}"
        )

    session_name = SESSION_IDENTIFIERS[session]
    logger.info(f"Fetching {session_name} results — {year} {gp} GP...")

    # Load the session (no telemetry needed for results)
    ff1_session = fastf1.get_session(year, gp, session)
    ff1_session.load(telemetry=False, weather=False, messages=False)

    event = ff1_session.event
    results_df: pd.DataFrame = ff1_session.results

    logger.info(f"Loaded {len(results_df)} driver entries for {session_name}")

    # Parse based on session type
    if session in ("R", "S"):
        drivers = _parse_race_results(results_df)
    elif session in ("Q", "SQ"):
        drivers = _parse_qualifying_results(results_df)
    else:
        # FP1, FP2, FP3
        drivers = _parse_practice_results(results_df)

    # Build session date string
    session_date: Optional[str] = None
    try:
        date_val = ff1_session.date
        if date_val is not None:
            if hasattr(date_val, "tzinfo") and date_val.tzinfo is not None:
                session_date = date_val.isoformat()
            else:
                session_date = date_val.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    except Exception as e:
        logger.warning(f"Could not parse session date: {e}")

    output = {
        "year":          year,
        "gp":            _safe_str(event.get("EventName")),
        "session":       session,
        "session_name":  session_name,
        "round_number":  int(event.get("RoundNumber", 0)),
        "country":       _safe_str(event.get("Country")),
        "location":      _safe_str(event.get("Location")),
        "circuit":       _safe_str(event.get("OfficialEventName", event.get("EventName"))),
        "date_utc":      session_date,
        "total_drivers": len(drivers),
        "results":       drivers,
    }

    logger.info(
        f"Successfully fetched {session_name} results: "
        f"{len(drivers)} drivers — {output['gp']} {year}"
    )
    return output


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import sys

    # Usage: python fast_f1_race_results.py [year] [gp] [session]
    #   gp can be a round number (int) or a GP/country name (str)
    #   e.g.: python fast_f1_race_results.py 2025 1 R
    #         python fast_f1_race_results.py 2025 Australia R
    _year = int(sys.argv[1]) if len(sys.argv) > 1 else 2025

    # Auto-convert to int if gp arg is a numeric round number, else keep as str
    _gp_raw = sys.argv[2] if len(sys.argv) > 2 else "5"
    _gp: str | int = int(_gp_raw) if _gp_raw.isdigit() else _gp_raw

    _session = sys.argv[3].upper() if len(sys.argv) > 3 else "R"

    data = fetch_session_results(_year, _gp, _session)
    print(json.dumps(data, indent=2, default=str))

