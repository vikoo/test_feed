from bs4 import BeautifulSoup
from googletrans import Translator

from cron.api_queries import query_get_latest_grand_prixes, mutation_post_feed, mutation_update_config, \
    query_get_config, mutation_post_weather, mutation_update_race_with_weather, mutation_update_weather, \
    query_old_feeds, mutation_delete_feed, mutation_update_feed
from cron.utils import *
import requests
import json
from datetime import datetime, timedelta

from cron.weather_utils import get_icon_url, get_weather_desc, convert_weather_api_json_to_strapi_json

#----------------------------------------------------------------------------------------------------------------
# common code
#----------------------------------------------------------------------------------------------------------------
def get_headers(is_f1_feed: bool) -> str:
    token = get_graphql_token(is_f1_feed)
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    return headers

#----------------------------------------------------------------------------------------------------------------
# Config relate code
#----------------------------------------------------------------------------------------------------------------
def get_config(is_f1_feed: bool) -> str:
    end_point = get_graphql_endpoint(is_f1_feed)

    response = requests.post(end_point, json={'query': query_get_config}, headers=get_headers(is_f1_feed))
    print(response.json())
    config_json = response.json()['data']['config']['data']['attributes']['feedJson']
    print(config_json)
    return config_json

def update_config(is_f1_feed, config_json_str) -> str:
    end_point = get_graphql_endpoint(is_f1_feed)

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

    response = requests.post(end_point, json={"query": mutation_update_config, "variables": variables}, headers=get_headers(is_f1_feed))
    print(response.json())

#----------------------------------------------------------------------------------------------------------------
# RSS FEEDs relate code
#----------------------------------------------------------------------------------------------------------------
async def post_feed(is_f1_feed, feed, feed_source):
    print(f"------> posting feed to strapi: {feed.title}")
    end_point = get_graphql_endpoint(is_f1_feed)

    feed_map = {'title': feed.title}
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

    # Define new values for feedJson
    variables = {"input": feed_map, "locale": "en"}
    # print(f"------> variables: {variables}")

    # Send the request
    response = requests.post(end_point, json={"query": mutation_post_feed, "variables": variables}, headers=get_headers(is_f1_feed))
    result = response.json()
    print(result)
    feed_id = result["data"]["createFeed"]["data"]["id"]
    print(f"feed_id : {feed_id}")

    # Initialize translator
    translator = Translator()

    # Translate title and description for other locales
    for locale in locales:

        translated_title_obj = await translator.translate(feed_map["title"], dest=locale)
        translated_desc_obj = await translator.translate(feed_map["description"], dest=locale)

        translated_title = translated_title_obj.text
        translated_desc = translated_desc_obj.text
        print(f"{locale} : title: {translated_title}")

        updated_map = feed_map.copy()
        updated_map['title'] = translated_title
        updated_map['description'] = translated_desc
        updated_map['guid'] = feed_map['guid'] + locale

        variables_update = {"input": updated_map, "locale": locale}
        # variables_update = {"input": updated_map, "locale": locale, "feedId": feed_id}
        # print(f"variable : {variables_update}")
        update_response = requests.post(
            end_point,
            json={"query": mutation_post_feed, "variables": variables_update},
            headers=get_headers(is_f1_feed),
        )
        print(f"Update Feed [{locale}] Response:", update_response.json())

# Fetch primary image from feed.link if feed.links is empty
def fetch_primary_image(url: str):
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

def fetch_old_feeds(is_f1_feed: bool, cutoff_date_str: str, start=0, limit=50):
    end_point = get_graphql_endpoint(is_f1_feed)
    variables = {"cutoffDate": cutoff_date_str, "limit": limit, "start": start}
    resp = requests.post(end_point, json={"query": query_old_feeds, "variables": variables}, headers=get_headers(is_f1_feed))
    resp.raise_for_status()
    return resp.json()["data"]["feeds"]["data"]

def delete_feed(is_f1_feed: bool, feed_id):
    end_point = get_graphql_endpoint(is_f1_feed)
    variables = {"id": feed_id}
    resp = requests.post(end_point, json={"query": mutation_delete_feed, "variables": variables}, headers=get_headers(is_f1_feed))
    resp.raise_for_status()
    return resp.json()
#----------------------------------------------------------------------------------------------------------------
# weather relate code
#----------------------------------------------------------------------------------------------------------------
def get_upcoming_races(is_f1_feed) -> str:
    end_point = get_graphql_endpoint(is_f1_feed)
    current_date = datetime.utcnow()
    current_date_str = current_date.isoformat() + "Z"
    variables = {
        "currentDate": current_date_str,
    }

    response = requests.post(end_point, json={'query': query_get_latest_grand_prixes, "variables": variables}, headers=get_headers(is_f1_feed))
    data = response.json()
    print(f"get_upcoming_races ---> {data}")
    return response.json()

def create_weather(is_f1_feed: bool, weather_json: str, race_id: str, lat: float, lon: float) -> str:
    # Define GraphQL endpoint
    end_point = get_graphql_endpoint(is_f1_feed)
    json_str = convert_weather_api_json_to_strapi_json(weather_json, race_id, lat, lon)
    variables = f"""
      {{
        "input": {json_str}
      }}
      """

    print(f"------> variables: {variables}")
    response = requests.post(end_point, json={'query': mutation_post_weather, "variables": variables}, headers=get_headers(is_f1_feed))
    data = response.json()
    print(f"create weather---> {data}")
    weather_id = data['data']['createWeather']['data']['id']
    print(weather_id)
    return weather_id

def update_weather_in_race(is_f1_feed: bool, weather_id: str, race_id: str) -> str:
    end_point = get_graphql_endpoint(is_f1_feed)
    variables = {
        "weatherId": weather_id,
        "raceId": race_id,
    }
    print(f"------> variables: {variables}")
    response = requests.post(end_point, json={'query': mutation_update_race_with_weather, "variables": variables}, headers=get_headers(is_f1_feed))
    data = response.json()
    print(f"update weather in race---> {data}")
    return response.json()


def update_weather(is_f1_feed: bool, weather_id: str, weather_json: str, race_id: str, lat: float, lon: float) -> str:
    end_point = get_graphql_endpoint(is_f1_feed)
    json_str = convert_weather_api_json_to_strapi_json(weather_json, race_id, lat, lon)
    variables = f"""
      {{
        "input": {json_str},
        "id": {weather_id}
      }}
      """
    print(f"------> variables: {variables}")
    response = requests.post(end_point, json={'query': mutation_update_weather, "variables": variables}, headers=get_headers(is_f1_feed))
    data = response.json()
    print(f"update weather ---> {data}")
    return response.json()
