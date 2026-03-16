"""
FastF1 Schedule Fetcher

Uses the fastf1 package to fetch the F1 Grand Prix schedule for a given year.
Each event includes all sessions (Practice 1/2/3, Qualifying, Sprint, Race)
with their UTC datetimes.

FastF1 docs: https://docs.fastf1.dev/
"""

import fastf1
from datetime import datetime
from typing import Optional
from loguru import logger


def fetch_f1_schedule(year: int) -> list[dict]:
    """
    Fetch the full F1 Grand Prix schedule for a given year using FastF1.

    Args:
        year (int): The championship year (e.g. 2025, 2026).

    Returns:
        list[dict]: A list of event dictionaries. Each dict contains:
            - round_number   (int)
            - event_name     (str)  – official event name
            - country        (str)
            - location       (str)  – circuit city
            - circuit_name   (str)
            - is_sprint      (bool) – True if the weekend contains a Sprint
            - sessions       (list[dict]) – ordered list of sessions:
                - name        (str)  e.g. "Practice 1", "Race"
                - date_utc    (str)  ISO-8601 UTC datetime or None

    Raises:
        Exception: Propagates any FastF1 / network errors.

    Example:
        >>> schedule = fetch_f1_schedule(2026)
        >>> for event in schedule:
        ...     print(event['round_number'], event['event_name'])
    """
    logger.info(f"Fetching F1 schedule for {year} using FastF1...")

    event_schedule = fastf1.get_event_schedule(year, include_testing=False)

    logger.info(f"Found {len(event_schedule)} events for {year}")

    schedule: list[dict] = []

    # Session column names used by FastF1 in the schedule DataFrame
    session_columns = [
        ("Session1", "Session1Date"),
        ("Session2", "Session2Date"),
        ("Session3", "Session3Date"),
        ("Session4", "Session4Date"),
        ("Session5", "Session5Date"),
    ]

    for _, row in event_schedule.iterrows():
        sessions: list[dict] = []

        for name_col, date_col in session_columns:
            session_name: str = row.get(name_col, "")
            session_date = row.get(date_col)

            # Skip empty / placeholder sessions
            if not session_name:
                continue

            # Convert pandas Timestamp → ISO-8601 string (UTC)
            date_utc: Optional[str] = None
            if session_date is not None:
                try:
                    ts = session_date
                    # Localise to UTC if the timestamp is tz-aware
                    if hasattr(ts, "tzinfo") and ts.tzinfo is not None:
                        date_utc = ts.isoformat()
                    else:
                        # Treat naive timestamps as UTC
                        date_utc = ts.strftime("%Y-%m-%dT%H:%M:%S+00:00")
                except Exception as e:
                    logger.warning(f"Could not parse date for {session_name}: {e}")

            sessions.append({
                "name": session_name,
                "date_utc": date_utc,
            })

        event: dict = {
            "round_number": int(row["RoundNumber"]),
            "event_name": str(row["EventName"]),
            "country": str(row["Country"]),
            "location": str(row["Location"]),
            "circuit_name": str(row.get("OfficialEventName", row["EventName"])),
            "is_sprint": bool(row.get("EventFormat", "") == "sprint"),
            "sessions": sessions,
        }

        schedule.append(event)
        logger.debug(f"  Round {event['round_number']}: {event['event_name']} ({event['country']})")

    logger.info(f"Successfully built schedule with {len(schedule)} events")
    return schedule


if __name__ == "__main__":
    import json

    YEAR = datetime.now().year

    schedule = fetch_f1_schedule(YEAR)

    print(json.dumps(schedule, indent=2, default=str))

