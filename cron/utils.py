import os
from datetime import datetime, timezone
from dotenv import load_dotenv
from dateutil import parser as date_parser

# Load environment variables from .env file - this is for local setup of token
load_dotenv()

#----------------------------------------------------------------------------------------------------------------
# CONFIG relate code
#----------------------------------------------------------------------------------------------------------------
# f1_graphql_end_point = "https://api-test.purplesector.club/graphql"  #"https://apiv2.purplesector.club/graphql"
# f1_graphql_token = os.getenv("F1_TEST_TOKEN")
f1_graphql_end_point = "https://apiv2.purplesector.club/graphql"
f1_graphql_token = os.getenv("F1_TOKEN")
moto_graphql_end_point = "https://api.wheelie.digisaint.com/graphql"
moto_graphql_token = os.getenv("MOTO_GP_TOKEN")

locales = {"de", "es", "fr", "it", "ja", "pt", "ru", "ko", "zh"}
# locales = {"it"}

def get_graphql_endpoint(is_f1_feed):
    if is_f1_feed:
        return f1_graphql_end_point
    else:
        return moto_graphql_end_point

def get_graphql_token(is_f1_feed):
    if is_f1_feed:
        return f1_graphql_token
    else:
        return moto_graphql_token

def get_feed_urls(is_f1_feed):
    if is_f1_feed:
        return f1_feed_urls
    else:
        return moto_feed_urls

#----------------------------------------------------------------------------------------------------------------
# RSS FEEDs relate code
#----------------------------------------------------------------------------------------------------------------
# URLs of the RSS feeds
f1_feed_urls = [
    "https://www.formula1.com/content/fom-website/en/latest/all.xml",
    "https://www.motorsport.com/rss/f1/news/",
    "https://www.gpfans.com/en/rss.xml",
    # "https://www.autosport.com/rss/f1/news/",
    "https://www.gpblog.com/en/sitemap/news.xml",
    # "https://flipboard.com/topic/formula1.rss"
]

moto_feed_urls = [
    "https://www.gpone.com/en/article-feed.xml",
    "https://www.motorsport.com/rss/motogp/news/",
    # "https://www.autosport.com/rss/motogp/news/",
    "https://flipboard.com/topic/motogp.rss"
]

url_to_id = {
    # F1
    "https://www.formula1.com/content/fom-website/en/latest/all.xml": "formula1",
    "https://www.motorsport.com/rss/f1/news/": "motorsport",
    "https://www.autosport.com/rss/f1/news/": "autosport",
    "https://www.gpblog.com/en/sitemap/news.xml": "gpblog",
    "https://www.gpfans.com/en/rss.xml":"gpfans",
    "https://flipboard.com/topic/formula1.rss":"flipboard",
    # moto GP
    "https://www.gpone.com/en/article-feed.xml":"gpone",
    "https://www.motorsport.com/rss/motogp/news/": "motorsport",
    "https://www.autosport.com/rss/motogp/news/": "autosport",
    "https://flipboard.com/topic/motogp.rss":"flipboard",
}

def parse_datetime_string(date_str: str) -> datetime:
    """
    Parse date string in multiple supported formats.

    Supports:
    - RFC 2822 format: "%a, %d %b %Y %H:%M:%S %z" (e.g., "Mon, 10 Feb 2026 19:16:24 +0100")
    - ISO 8601 format: "%Y-%m-%dT%H:%M:%S%z" (e.g., "2026-02-10T19:16:24+0100")
    - Flexible parsing via dateutil parser as fallback

    Args:
        date_str: Date string to parse

    Returns:
        datetime object with timezone info

    Raises:
        ValueError: If the date string cannot be parsed in any format
    """
    # Try the RFC 2822 format first
    try:
        return datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %z")
    except ValueError:
        pass

    # If that fails, try ISO 8601 format
    try:
        return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        pass

    # If both fail, use dateutil parser for flexible parsing
    try:
        return date_parser.parse(date_str)
    except Exception as e:
        raise ValueError(f"Failed to parse date string '{date_str}': {e}")

def get_epoch(date_str: str) -> int:
    """
    Convert date string to epoch timestamp.

    Args:
        date_str: Date string in supported formats

    Returns:
        Integer epoch timestamp (seconds since Unix epoch)
    """
    print(date_str)
    try:
        dt = parse_datetime_string(date_str)
        return int(dt.timestamp())
    except ValueError as e:
        print(f"Failed to parse date: {date_str} - {e}")
        # Return current epoch as fallback
        return int(datetime.now(timezone.utc).timestamp())


def get_current_epoch() :
    return str(int(datetime.now().timestamp() * 1000))

def current_datetime_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

