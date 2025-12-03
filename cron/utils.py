import os
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env file - this is for local setup of token
load_dotenv()

#----------------------------------------------------------------------------------------------------------------
# CONFIG relate code
#----------------------------------------------------------------------------------------------------------------
f1_graphql_end_point = "https://api.purplesector.club/graphql"
f1_graphql_token = os.getenv("F1_TOKEN")
moto_graphql_end_point = "https://api.wheelie.club/graphql"
moto_graphql_token = os.getenv("MOTO_GP_TOKEN")

locales = {"de", "es", "fr", "it", "ja", "pt", "zh", "ru", "ko"}
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

def get_epoch(date_str) :
    # Parse the date string using the appropriate format
    dt = datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %z")

    # Convert the datetime to an epoch timestamp
    epoch_timestamp = dt.timestamp()
    return epoch_timestamp
