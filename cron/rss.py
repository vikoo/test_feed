import asyncio

import feedparser
from datetime import timezone, timedelta
from cron.apis import *
from dotenv import load_dotenv

# Load environment variables from .env file - this is for local setup of token
load_dotenv()

print("Using Token 1:", f1_graphql_token[:5] + "*****")  # Masking token
print("Using Token 2:", moto_graphql_token[:5] + "*****")

def fetch_and_process_feeds(is_f1_feed: bool):
  # GET CONFIG
  config = get_config(is_f1_feed)

  feed_update_map = {}
  # GET LAST FEED TIME
  feed_urls = get_feed_urls(is_f1_feed)
  for index, feed_url in enumerate(feed_urls):
    feeds = feedparser.parse(feed_url)
    print(f" feed len: {len(feeds)}")
    # in case xml is getting downloaded rather than shown in browser entries will be empty.
    # in this case call the normal API like below to fetch the feeds
    if len(feeds.entries) == 0:
      headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
      }
      response = requests.get(feed_url, headers=headers)
      if response.status_code == 200:
        feeds = feedparser.parse(response.content)
      else:
        print(f"Failed to fetch feed: {response.status_code} - {feed_url}")

    # get feed source and last feed time from config
    feed_source = url_to_id[feed_url]
    config_date = config[feed_source]

    # Checks for None, empty string from server config, if null or empty then config date will be 1 day back
    if not config_date:
      config_date = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%a, %d %b %Y %H:%M:%S %z")

    print(f"------> source: {feed_source} - date: {config_date} - url: {feed_url}")

    # date to fill in update config
    feed_date = ""
    is_published_date_present = True

    # Check if 'published' exists, otherwise reverse and add current date-time
    for entry in feeds.entries:
      if "published" not in entry:
        is_published_date_present = False
        feeds.entries.reverse()
        for e in feeds.entries:
          e["published"] = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
        break  # Only reverse once when at least one entry lacks 'published'

    # if date is GMT then
    for entry in feeds.entries:
      entry["published"] = entry["published"].replace("GMT", "+0000")


    # Sort feeds by pubDate
    entries = sorted(feeds.entries, key=lambda x: datetime.strptime(x["published"], "%a, %d %b %Y %H:%M:%S %z"))
    print(f"------> source: {feed_source} - size: {len(entries)}")

    # if published date is present then parse based on date time
    if is_published_date_present:
      for feed in entries:
        feed_date = feed.published
        feed_epoch = get_epoch(feed_date)
        config_epoch = get_epoch(config_date)
        print(f"------># feed date: {feed_date}")
        if feed_epoch > config_epoch:
          print(f"------>## processing feed title: {feed.title}")
          print(f"------>## processing feed: {feed}")
          process_feed(is_f1_feed, feed, feed_source)
    else :
      # parse based on guid
      is_last_feed_found = False
      for feed in entries:
        feed_date = feed.id
        print(f"------># feed guid: {feed_date}")
        if feed_date == config_date:
          is_last_feed_found = True
          continue
        else:
          if not is_last_feed_found:
            continue

        if is_last_feed_found:
          print(f"------>## guid processing feed title: {feed.title}")
          print(f"------>## guid processing feed: {feed}")
          process_feed(is_f1_feed, feed, feed_source)

    feed_update_map[feed_source] = feed_date

  json_str = json.dumps(feed_update_map)
  update_config(is_f1_feed, json_str)

def process_feed(is_f1_feed: bool, feed, feed_source):
  asyncio.run(post_feed(is_f1_feed, feed, feed_source))


if __name__ == "__main__":
  print(f"------------- FETCHING F1 FEEDS ------------------")
  fetch_and_process_feeds(True)
  print(f"------------- FETCHING MOTO GP FEEDS ------------------")
  fetch_and_process_feeds(False)
