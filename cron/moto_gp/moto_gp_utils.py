import re
from datetime import datetime, timezone

def current_time_utc_iso() -> str:
    """
    Return current UTC time in format 'YYYY-MM-DDTHH:MM:SSZ'
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def normalize_iso_timezone(dt_str: str) -> str:
    """
    Converts timezone offsets like:
      +0700 → +07:00
      -0530 → -05:30
      +07   → +07:00
      Z     → +00:00
    to valid ISO-8601 for Python.
    """
    if not dt_str:
        return ""

    dt_str = dt_str.replace("Z", "+00:00")

    # Fix timezone without colon: +0700 / -0530
    dt_str = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", dt_str)

    # Fix timezone without minutes: +07 / -05
    dt_str = re.sub(r"([+-]\d{2})$", r"\1:00", dt_str)

    return dt_str


def to_utc(dt_str):
    if not dt_str:
        return None

    dt_str = normalize_iso_timezone(dt_str)
    if not dt_str:
        return None

    dt = datetime.fromisoformat(dt_str)

    return dt.astimezone(timezone.utc).isoformat()