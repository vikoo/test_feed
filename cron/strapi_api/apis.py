from bs4 import BeautifulSoup
from googletrans import Translator

from cron.strapi_api.api_queries import query_get_latest_grand_prixes, mutation_post_feed, \
    mutation_update_config_for_feeds, \
    query_get_config, mutation_post_weather, mutation_update_race_with_weather, mutation_update_weather, \
    query_old_feeds, mutation_delete_feed, query_old_votes, mutation_delete_vote, \
    query_old_vote_counts, mutation_delete_vote_count, query_get_seasons, query_get_grand_prixes_for_year, \
    mutation_post_season, mutation_update_config_for_season, query_get_tracks, mutation_post_grand_prix, \
    mutation_post_race, mutation_update_race_with_time, mutation_update_config_for_gp
from cron.utils import *
import requests
import re
import json
from datetime import datetime, timezone

from cron.weather.weather_utils import convert_weather_api_json_to_strapi_json

#----------------------------------------------------------------------------------------------------------------
# common code
#----------------------------------------------------------------------------------------------------------------
def get_headers(is_f1_feed: bool) -> dict[str, str]:
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
    config_json = response.json()['data']['config']['data']['attributes']
    print(config_json)
    return config_json

def get_config_for_feeds(is_f1_feed: bool) -> str:
    end_point = get_graphql_endpoint(is_f1_feed)

    response = requests.post(end_point, json={'query': query_get_config}, headers=get_headers(is_f1_feed))
    print(response.json())
    config_json = response.json()['data']['config']['data']['attributes']['feedJson']
    print(config_json)
    return config_json

def update_config_for_feeds(is_f1_feed, config_json_str) -> None:
    end_point = get_graphql_endpoint(is_f1_feed)

    # Define new values for feedJson
    variables = f"""
    {{
    "input": {{
      "feedJson": {config_json_str}
    }}
  }}
  """
    print(f"------> update_config_for_feeds config_json_str: {config_json_str}")
    print(f"------> update_config_for_feeds variables: {variables}")

    response = requests.post(end_point, json={"query": mutation_update_config_for_feeds, "variables": variables}, headers=get_headers(is_f1_feed))
    print(response.json())

#----------------------------------------------------------------------------------------------------------------
# RSS FEEDs relate code
#----------------------------------------------------------------------------------------------------------------
async def post_feed(is_f1_feed, feed, feed_source):
    print(f"------> posting feed to strapi: {feed.title}")
    end_point = get_graphql_endpoint(is_f1_feed)

    feed_map = {'title': feed.title}
    summary = process_feed_desc(feed.summary)
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

    # Check for GraphQL errors
    if "errors" in result:
        print("❌ GraphQL errors:", result["errors"])
        return

    # Check that createFeed->data exists
    feed_data = result.get("data", {}).get("createFeed", {}).get("data")
    if not feed_data:
        print("❌ No feed data in response:", result)
        return

    feed_id = feed_data["id"]
    print(f"feed_id : {feed_id}")

    # Initialize translator
    translator = Translator()

    # Translate title and description for other locales
    for locale in locales:
        try:
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
                # json={"query": mutation_update_feed, "variables": variables_update},
                headers=get_headers(is_f1_feed),
            )
            print(f"Update Feed [{locale}] Response:", update_response.json())
        except Exception as e:
            print(f"⚠️ Translation failed for locale {locale}: {e}")
            print(f"   Skipping {locale} translation for this feed")

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

def fetch_old_feeds(is_f1_feed: bool, cutoff_date_str: str, start=0, limit=50, lang: str = "en"):
    end_point = get_graphql_endpoint(is_f1_feed)
    variables = {"cutoffDate": cutoff_date_str, "limit": limit, "start": start, "locale": lang}
    resp = requests.post(end_point, json={"query": query_old_feeds, "variables": variables}, headers=get_headers(is_f1_feed))
    resp.raise_for_status()
    return resp.json()["data"]["feeds"]["data"]

def fetch_old_votes(is_f1_feed: bool, cutoff_date_str: str, start=0, limit=50):
    end_point = get_graphql_endpoint(is_f1_feed)
    variables = {"cutoffDate": cutoff_date_str, "limit": limit, "start": start}
    resp = requests.post(end_point, json={"query": query_old_votes, "variables": variables}, headers=get_headers(is_f1_feed))
    resp.raise_for_status()
    print(f"json: ${resp.json()}")
    return resp.json()["data"]["votes"]["data"]

def fetch_old_vote_counts(is_f1_feed: bool, cutoff_date_str: str, start=0, limit=50):
    end_point = get_graphql_endpoint(is_f1_feed)
    variables = {"cutoffDate": cutoff_date_str, "limit": limit, "start": start}
    resp = requests.post(end_point, json={"query": query_old_vote_counts, "variables": variables}, headers=get_headers(is_f1_feed))
    resp.raise_for_status()
    print(f"json: ${resp.json()}")
    return resp.json()["data"]["voteCounts"]["data"]

def delete_feed(is_f1_feed: bool, feed_id):
    end_point = get_graphql_endpoint(is_f1_feed)
    variables = {"id": feed_id}
    resp = requests.post(end_point, json={"query": mutation_delete_feed, "variables": variables}, headers=get_headers(is_f1_feed))
    resp.raise_for_status()
    return resp.json()

def delete_vote(is_f1_feed: bool, feed_id):
    end_point = get_graphql_endpoint(is_f1_feed)
    variables = {"id": feed_id}
    resp = requests.post(end_point, json={"query": mutation_delete_vote, "variables": variables}, headers=get_headers(is_f1_feed))
    resp.raise_for_status()
    return resp.json()

def delete_vote_count(is_f1_feed: bool, feed_id):
    end_point = get_graphql_endpoint(is_f1_feed)
    variables = {"id": feed_id}
    resp = requests.post(end_point, json={"query": mutation_delete_vote_count, "variables": variables}, headers=get_headers(is_f1_feed))
    resp.raise_for_status()
    return resp.json()

def process_feed_desc(description: str) -> str:
    """
    Removes <img> and <br> tags (in any case or format) from the given text.
    """
    if not description:
        return ""

    # Remove all <img ...> tags
    description = re.sub(r'<img[^>]*>', '', description, flags=re.IGNORECASE)

    # Remove all <br>, <br/>, <br /> (case-insensitive)
    description = re.sub(r'<br\s*/?>', '', description, flags=re.IGNORECASE)

    # Remove <a ...>...</a> including inner text
    description = re.sub(r'<a\b[^>]*>.*?</a>', '', description, flags=re.IGNORECASE | re.DOTALL)

    return description.strip()

#----------------------------------------------------------------------------------------------------------------
# weather relate code
#----------------------------------------------------------------------------------------------------------------
def get_upcoming_races(is_f1_feed) -> str:
    end_point = get_graphql_endpoint(is_f1_feed)
    current_date =  datetime.now(timezone.utc)
    current_date_str = current_date.isoformat() + "Z"
    variables = {
        "currentDate": current_date_str,
    }
    print(f"get_upcoming_races ------> variables: {variables}")

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

    print(f"create_weather ------> variables: {variables}")
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
    print(f"update_weather_in_race ------> variables: {variables}")
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
    print(f"update_weather ------> variables: {variables}")
    response = requests.post(end_point, json={'query': mutation_update_weather, "variables": variables}, headers=get_headers(is_f1_feed))
    data = response.json()
    print(f"update weather ---> {data}")
    return response.json()


#----------------------------------------------------------------------------------------------------------------
# schedule relate code
#----------------------------------------------------------------------------------------------------------------
def get_seasons(is_f1_feed: bool) -> str:
    end_point = get_graphql_endpoint(is_f1_feed)
    print(f"fetching seasons -->")
    response = requests.post(end_point, json={'query': query_get_seasons}, headers=get_headers(is_f1_feed))
    print(response.json())
    return response.json()

def get_tracks(is_f1_feed: bool) -> str:
    end_point = get_graphql_endpoint(is_f1_feed)
    print(f"fetching tracks -->")
    response = requests.post(end_point, json={'query': query_get_tracks}, headers=get_headers(is_f1_feed))
    # print(response.json())
    return response.json()

def get_grand_prix_races_for_year(is_f1_feed: bool, year: str):
    end_point = get_graphql_endpoint(is_f1_feed)
    variables = {
        "season": year,
    }
    print(f"get_grand_prix_races_for_year --> variables: {variables}")

    response = requests.post(end_point, json={'query': query_get_grand_prixes_for_year, "variables": variables}, headers=get_headers(is_f1_feed))
    data = response.json()
    grand_prixes = data.get("data", {}).get("grandPrixes", {}).get("data", [])
    races = data.get("data", {}).get("races", {}).get("data", [])
    print(f"grand_prixes: {grand_prixes}")
    print(f"races: {races}")
    return grand_prixes, races

def create_season(is_f1_feed: bool, season_year: str) -> str:
    # Define GraphQL endpoint
    end_point = get_graphql_endpoint(is_f1_feed)
    season = {
        "year": season_year,
        "name": f"{season_year} Season"
    }
    json_str = json.dumps(season)
    variables = f"""
      {{
        "input": {json_str}
      }}
      """

    print(f"create_season ------> variables: {variables}")
    response = requests.post(end_point, json={'query': mutation_post_season, "variables": variables}, headers=get_headers(is_f1_feed))
    data = response.json()
    print(f"create_season---> {data}")
    season_id = data['data']['createSeason']['data']['id']
    print(season_id)
    return season_id


def update_config_for_season(is_f1_feed: bool, driver_standings_json_str: str, team_standings_json_str: str) -> None:
    end_point = get_graphql_endpoint(is_f1_feed)

    # Define new values for feedJson
    variables = f"""
    {{
        "input": {{
          "driverStandingsForSeasonJson": {driver_standings_json_str},
          "teamStandingsForSeasonJson": {team_standings_json_str},
          "driverTeamTrackSeasonTyre": "{get_current_epoch()}"
        }}
    }}
  """
    print(f"------> update_config_for_season variables: {variables}")

    response = requests.post(end_point, json={"query": mutation_update_config_for_season, "variables": variables}, headers=get_headers(is_f1_feed))
    print(response.json())

def update_config_for_gp(is_f1_feed: bool) -> None:
    end_point = get_graphql_endpoint(is_f1_feed)

    # Define new values for feedJson
    variables = f"""
    {{
        "input": {{
          "grandPrixRace": "{get_current_epoch()}"
        }}
    }}
  """
    print(f"------> update_config_for_gp variables: {variables}")

    response = requests.post(end_point, json={"query": mutation_update_config_for_gp, "variables": variables}, headers=get_headers(is_f1_feed))
    print(response.json())

def create_grand_prix(is_f1_feed: bool, json_str: str) -> str:
    # Define GraphQL endpoint
    end_point = get_graphql_endpoint(is_f1_feed)
    variables = f"""
      {{
        "input": {json_str}
      }}
      """

    print(f"create_grand_prix ------> variables: {variables}")
    response = requests.post(end_point, json={'query': mutation_post_grand_prix, "variables": variables}, headers=get_headers(is_f1_feed))
    print(f"create_grand_prix response: {response}")
    data = response.json()
    print(f"create_grand_prix---> {data}")
    gp_id = data['data']['createGrandPrix']['data']['id']
    print(f"gP ID: {gp_id}")
    return gp_id

def create_race(is_f1_feed: bool, json_str: str) -> str:
    # Define GraphQL endpoint
    end_point = get_graphql_endpoint(is_f1_feed)
    variables = f"""
      {{
        "input": {json_str}
      }}
      """

    print(f"create_race ------> variables: {variables}")
    response = requests.post(end_point, json={'query': mutation_post_race, "variables": variables}, headers=get_headers(is_f1_feed))
    data = response.json()
    print(f"create_race---> {data}")
    race_id = data['data']['createRace']['data']['id']
    print(f"race ID: {race_id}")
    return race_id

def update_time_in_race(is_f1_feed: bool, start_time: str, race_id: str) -> str:
    end_point = get_graphql_endpoint(is_f1_feed)
    variables = {
        "startTime": start_time,
        "raceId": race_id,
    }
    print(f"update_time_in_race ------> variables: {variables}")
    response = requests.post(end_point, json={'query': mutation_update_race_with_time, "variables": variables}, headers=get_headers(is_f1_feed))
    data = response.json()
    print(f"update_time_in_race in race---> {data}")
    return response.json()