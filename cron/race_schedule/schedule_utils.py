import argparse
from datetime import datetime, timezone

def valid_year(value):
    year = int(value)
    current_year = datetime.now(timezone.utc).year + 1   # allow next season

    if year < 1949 or year > current_year:
        raise argparse.ArgumentTypeError(
            f"Year must be between 1949 and {current_year}"
        )

    return year