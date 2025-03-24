import asyncio

import os
import feedparser
import requests
import json
from datetime import datetime, timezone, timedelta

from bs4 import BeautifulSoup

# switch this flag for moto GP and F1 related feed
is_F1 = True

#----------------------------------------------------------------------------------------------------------------
# CONFIG relate code
#----------------------------------------------------------------------------------------------------------------
f1_graphql_end_point = "https://api.purplesector.club/graphql"
f1_graphql_token = os.getenv("F1_TOKEN")
moto_graphql_end_point = "https://api.wheelie.club/graphql"
moto_graphql_token = os.getenv("MOTO_GP_TOKEN")

def get_graphql_endpoint():
  if is_F1:
    return f1_graphql_end_point
  else:
    return moto_graphql_end_point

def get_graphql_token():
  if is_F1:
    return f1_graphql_token
  else:
    return moto_graphql_token

def get_feed_urls():
  if is_F1:
    return f1_feed_urls
  else:
    return moto_feed_urls

def get_config():
  # Define GraphQL endpoint
  end_point = get_graphql_endpoint()

  token = get_graphql_token()
  headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {token}"
  }

  # GraphQL query
  query = """
  {
    config {
        data {
            id
            attributes {
                feedJson
            }
        }
    }
  }
  """
  # Send request
  response = requests.post(end_point, json={'query': query}, headers=headers)
  # Print response
  print(response.json())
  config_json = response.json()['data']['config']['data']['attributes']['feedJson']
  print(config_json)
  return config_json

def update_config(config_json_str):
  # Define GraphQL endpoint
  end_point = get_graphql_endpoint()

  token = get_graphql_token()
  headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {token}"
  }

  mutation = """
  mutation UpdateConfig($input: ConfigInput!) {
    updateConfig(data: $input) {
        data {
            id
            attributes {
                feedJson
            }
        }
    }
  }
  """

  # Define new values for feedJson
  variables = f"""
    {{
    "input": {{
      "feedJson": {config_json_str}
    }}
  }}
  """
  print(f"------> config_json_str: {config_json_str}")
  print(f"------> variables: {variables}")

  # Send the request
  response = requests.post(end_point, json={"query": mutation, "variables": variables}, headers=headers)
  print(response.json())

def post_feed(feed_url, feed, feed_source):
  print(f"------> posting feed to strapi: {feed.title}")
  # Define GraphQL endpoint
  end_point = get_graphql_endpoint()

  token = get_graphql_token()
  headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {token}"
  }

  mutation = """
  mutation PostFeed($input: FeedInput!) {
    createFeed(data: $input) {
        data {
            id
        }
    }
  }
  """
  feed_map = {}
  feed_map['title'] = feed.title
  summary = feed.summary.replace("<br>", "").replace("<br />", "").replace("<br/>", "").replace("<BR>", "").replace("<BR/>", "").replace("<BR />", "")
  feed_map['description'] = summary
  feed_map['guid'] = feed.id

  # Convert to datetime object
  dt = datetime.strptime(feed.published, "%a, %d %b %Y %H:%M:%S %z")
  # Convert datetime to ISO format string
  json_date = dt.isoformat()
  feed_map['pubDate'] = json_date

  feed_map['source'] = feed_source + ".com"
  feed_map['link'] = feed.link

  # if feed has image urls then get that
  if feed.links:
    type_to_href = {item['type']: item['href'] for item in feed.links if 'type' in item}
    print(f"---> type_to_href: {type_to_href}")
    feed_map['imageUrl'] = type_to_href.get('image/jpeg') or type_to_href.get('image/webp') or type_to_href.get('image/png')

  # if feed does not have image url then get it from article
  if not feed_map['imageUrl']:
    primary_image = fetch_primary_image(feed.link)
    if primary_image:
      feed_map['imageUrl'] = primary_image

  json_str = json.dumps(feed_map)
  # Define new values for feedJson
  variables = f"""
  {{
    "input": {json_str}
  }}
  """
  print(f"------> variables: {variables}")

  # Send the request
  response = requests.post(end_point, json={"query": mutation, "variables": variables}, headers=headers)
  print(response.json())

# Fetch primary image from feed.link if feed.links is empty
def fetch_primary_image(url):
  try:
    response = requests.get(url, timeout=5)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")
    img_tag = soup.find("meta", property="og:image")
    if img_tag and img_tag["content"]:
      return img_tag["content"]
  except Exception as e:
    print(f"Error fetching primary image: {e}")
  return None

#----------------------------------------------------------------------------------------------------------------
# RSS FEEDs relate code
#----------------------------------------------------------------------------------------------------------------
# URLs of the RSS feeds
f1_feed_urls = [
  "https://www.formula1.com/content/fom-website/en/latest/all.xml",
  "https://www.motorsport.com/rss/f1/news/",
  "https://www.gpfans.com/en/rss.xml",
  # "https://www.autosport.com/rss/f1/news/",
  "https://www.gpblog.com/en/rss/index.xml",
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
  "https://www.gpblog.com/en/rss/index.xml": "gpblog",
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

def fetch_and_process_feeds():
  # GET CONFIG
  config = get_config()

  feed_update_map = {}
  # GET LAST FEED TIME
  feed_urls = get_feed_urls()
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
          process_feed(feed_url, feed, feed_source)
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
          process_feed(feed_url, feed, feed_source)

    feed_update_map[feed_source] = feed_date

  json_str = json.dumps(feed_update_map)
  update_config(json_str)
  # if is_F1 :
  #   asyncio.run(send_message("F1 Feeds updated"))
  # else:
  #   asyncio.run(send_message("Moto GP Feeds updated"))
    # update config with last update for the feed url

def process_feed(feed_url, feed, feed_source):
  # push feed to strapi
  post_feed(feed_url, feed, feed_source)
  # Notify Telegram
  # asyncio.run(notify_telegram(feed_url, feed, feed_source))

if __name__ == "__main__":
  print(f"------------- FETCHING F1 FEEDS ------------------")
  fetch_and_process_feeds()
  print(f"------------- FETCHING MOTO GP FEEDS ------------------")
  is_F1 = False
  fetch_and_process_feeds()
