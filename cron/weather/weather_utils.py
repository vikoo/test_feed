import os
import requests
import json
from datetime import datetime, timedelta, timezone
from astral import LocationInfo
from astral.sun import sun
import pytz
from dotenv import load_dotenv

# Load environment variables from .env file - this is for local setup of token
load_dotenv()

WEATHER_API_KEY = os.getenv("TOMORROW_IO_API_KEY")
GRAND_PRIX_JSON_FILE_NAME_F1 = "grand_prix_data_f1.json"
GRAND_PRIX_JSON_FILE_NAME_MOTO = "grand_prix_data_moto.json"

#-----------------------------------------------------------------------------------
# weather api utils to fetch weather data from tomorrow.io
#-----------------------------------------------------------------------------------

# fetches the current weather
# used during race time
def fetch_current_weather(lat: float, lon: float) -> str:
    url = f"https://api.tomorrow.io/v4/weather/realtime?location={lat},{lon}&apikey={WEATHER_API_KEY}"
    r = requests.get(url)
    r.raise_for_status()
    return r.json()

# fetches the hourly weather for next 5 days
# used for race week
def fetch_hourly_weather(lat: float, lon: float) -> str:
    url = f"https://api.tomorrow.io/v4/weather/forecast?location={lat},{lon}&timesteps=1h&apikey={WEATHER_API_KEY}"
    r = requests.get(url)
    r.raise_for_status()
    return r.json()


BASE_URL = "https://github.com/Tomorrow-IO-API/tomorrow-weather-codes/blob/master/V2_icons/large/png/"
def get_icon_url(code: str, lat: float, lon: float, time_str: str) -> str:
    filename = weather_code_to_icon_mapping.get(code)
    print(f"icon file name: ${filename}")
    if not filename:
        # if file name not found then it's a generic code.
        # we need to append 0 for day and 1 for night to get the icon.
        is_day = is_day_or_night(lat, lon, time_str)
        print(f"is_day: ${is_day}")
        if is_day == "day":
            filename = weather_code_to_icon_mapping.get(code + "0")
        else:
            filename = weather_code_to_icon_mapping.get(code + "1")

        print(f"new icon file name: ${filename}")
        if not filename:
            return ""
        return BASE_URL + filename + "?raw=true"
    return BASE_URL + filename + "?raw=true"

def get_weather_desc(code: str) -> str:
    desc = weather_codes_to_desc_mapping.get(code)
    if not desc:
        return ""
    else:
        return desc

def is_day_or_night(lat: float, lon: float, time_str: str) -> str:
    """
    Given latitude, longitude, and UTC time string in format 'YYYY-MM-DDTHH:MM:SSZ',
    return 'day' or 'night'.
    """
    # Parse time string as UTC datetime
    dt_utc = datetime.fromisoformat(time_str.replace("Z", "+00:00"))

    # Define location
    location = LocationInfo(latitude=lat, longitude=lon, timezone="UTC")

    # Get sunrise/sunset for the given date
    s = sun(location.observer, date=dt_utc.date(), tzinfo=pytz.UTC)

    sunrise = s["sunrise"]
    sunset = s["sunset"]

    return "day" if sunrise <= dt_utc <= sunset else "night"

def get_weather_for_time(weather_json, target_time_str):
    """
    Return the weather object closest to the given target time.

    Args:
        weather_json (dict): JSON containing 'timelines' -> 'hourly'
        target_time_str (str): ISO 8601 datetime string with 'Z' (e.g., '2025-09-20T12:00:00.000Z')

    Returns:
        dict: Closest weather object from 'hourly', or None if no data
    """

    # Parse target time as UTC-aware datetime
    try:
        target_time = datetime.fromisoformat(target_time_str.replace("Z", "+00:00"))
    except ValueError:
        return None

    now = datetime.now(timezone.utc)
    if target_time < now:
        print(f"skipping this as event is done...")
        return None

    hourly_data = weather_json.get("timelines", {}).get("hourly", [])
    if not hourly_data:
        return None

    # Find the weather object closest to the target time
    closest_weather = min(
        hourly_data,
        key=lambda w: abs(datetime.fromisoformat(w["time"].replace("Z", "+00:00")) - target_time)
    )

    return closest_weather

def get_current_weather_from_json(weather_json):
    """
    Return the current weather object from a JSON that has only current weather.

    Args:
        weather_json (dict): JSON containing 'data' for current weather

    Returns:
        dict or None: Current weather object with 'time' and 'values', or None if missing
    """
    return weather_json.get("data", None)

def convert_weather_api_json_to_strapi_json(weather_json: str, race_id: str, lat: float, lon: float) -> str:
    weather_map = {'temp': weather_json["values"]["temperature"]}
    weather_map['feelsLike'] = weather_json["values"]["temperatureApparent"]
    weather_map['humidity'] = weather_json["values"]["humidity"]
    weather_map['windSpeed'] = weather_json["values"]["windSpeed"]
    weather_map['windGust'] = weather_json["values"]["windGust"]
    weather_map['windDirection'] = weather_json["values"]["windDirection"]
    weather_map['visibility'] = weather_json["values"]["visibility"]
    weather_map['time'] = weather_json["time"]
    weather_map['precipitationProbability'] = weather_json["values"]["precipitationProbability"]
    weather_code = str(weather_json["values"]["weatherCode"])
    weather_map['weatherDesc'] = get_weather_desc(weather_code)
    weather_map['cloudPercentage'] = weather_json["values"]["cloudBase"]
    weather_map['rainIntensity'] = weather_json["values"]["rainIntensity"]
    weather_map['weatherCode'] = weather_json["values"]["weatherCode"]
    weather_map['iconUrl'] = get_icon_url(weather_code, lat, lon, weather_map['time'])
    weather_map['race'] = race_id
    json_str = json.dumps(weather_map)
    return json_str

#-----------------------------------------------------------------------------------
# grand prix data and race data processing utils
#-----------------------------------------------------------------------------------

def get_track_coordinates(data):
    """
    Extract latitude and longitude from the track object
    in the first grandPrix entry. Returns (None, None) if not found.

    Args:
        data (dict): JSON response from the API

    Returns:
        tuple: (latitude, longitude)
    """
    try:
        grand_prixes = data.get("data", {}).get("grandPrixes", {}).get("data", [])
        if not grand_prixes:
            return None, None

        track_data = grand_prixes[0].get("attributes", {}).get("track", {}).get("data", {})
        if not track_data:
            return None, None

        track_attrs = track_data.get("attributes", {})
        latitude = track_attrs.get("latitude")
        longitude = track_attrs.get("longitude")

        return latitude, longitude
    except Exception:
        # In case JSON structure changes or keys are missing
        return None, None

def get_races_from_json(data: str):
    if not data:
        return {}
    else:
        return data.get("data", {}).get("races", {}).get("data", [])

def is_race_time_in_now_window(start_time_str):
    """
    Check if the current UTC time is between start_time and start_time + 3 hours.

    Args:
        start_time_str (str): ISO 8601 datetime string (e.g., "2025-09-21T11:00:00.000Z")

    Returns:
        bool: True if current UTC time is within the 3-hour window, else False
    """
    if not start_time_str:
        return False

    # Parse start_time string into timezone-aware datetime
    start_time = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))

    # End time = start_time + 3 hours
    end_time = start_time + timedelta(hours=3)

    # Current UTC time
    now = datetime.now(timezone.utc)

    # Check if now is within the window
    return start_time <= now <= end_time


#-----------------------------------------------------------------------------------
# utils for getting grand prix data and saving it to json file and read it.
#-----------------------------------------------------------------------------------
def check_json_outdated(data: str) -> bool:
    if not data:
        return True

    print(f"data to check: {data}")
    races = data.get("data", {}).get("races", {}).get("data", [])

    # Get the single Race startTime
    race_time = next(
        (race["attributes"]["startTime"] for race in races if race["attributes"]["type"] == "Race"),
        None  # fallback if not found
    )

    print(race_time)
    if race_time:
        # Parse ISO string into datetime (handle 'Z' as UTC)
        race_time = datetime.fromisoformat(race_time.replace("Z", "+00:00"))

        # Add 3 hours
        race_time_plus_3 = race_time + timedelta(hours=3)

        # Back to ISO string with Z
        new_time_str = race_time_plus_3.isoformat().replace("+00:00", "Z")

        print(f"new_time_str: {new_time_str}")
        # Get current UTC time
        current_time = datetime.now(timezone.utc)

        if current_time > race_time:
            print("✅ Current time is after the race start time. invalidate json and fetch next GP")
            return True
        else:
            print("you are in race week.")
            return False

    else:
        print(f"no race time found: so fetch the fresh the json")
        return True

def save_grandprix_json(data: str, is_for_f1: bool) -> str:

    # Ensure cron folder exists
    weather_dir = os.path.join("cron", "weather")
    os.makedirs(weather_dir, exist_ok=True)

    # Build path
    filepath = os.path.join(weather_dir, get_local_json_file_name(is_for_f1))

    # Delete file if it exists
    if os.path.exists(filepath):
        os.remove(filepath)

    # Save JSON file
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"✅ Saved file to {filepath}")
    return filepath

def read_grand_prix_json(is_for_f1: bool):
    """
    Read JSON data from the cron/ folder.
    Returns an empty dict {} if file does not exist or file is empty/invalid.
    """
    weather_dir = os.path.join("cron", "weather")
    filepath = os.path.join(weather_dir, get_local_json_file_name(is_for_f1))

    # Check if file exists
    if not os.path.exists(filepath):
        return {}

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Return {} if file exists but contains nothing
            return data if data else {}
    except (json.JSONDecodeError, OSError):
        # If file is empty or invalid JSON
        return {}

def delete_grandprix_json(is_for_f1: bool) -> str:

    # Ensure cron folder exists
    weather_dir = os.path.join("cron", "weather")
    os.makedirs(weather_dir, exist_ok=True)

    # Build path
    filepath = os.path.join(weather_dir, get_local_json_file_name(is_for_f1))

    # Delete file if it exists
    if os.path.exists(filepath):
        os.remove(filepath)

    # Save JSON file
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump("", f, indent=2, ensure_ascii=False)

    print(f"✅ cleared json data for file: {filepath}")
    return filepath

def get_local_json_file_name(is_for_f1: bool) -> str:
    if is_for_f1:
        return GRAND_PRIX_JSON_FILE_NAME_F1
    else:
        return GRAND_PRIX_JSON_FILE_NAME_MOTO


weather_codes_to_desc_mapping = {
    "0": "",
    "1000": "Clear, Sunny",
    "10000": "Clear, Sunny",
    "10001": "Clear",
    "1001": "Cloudy",
    "10010": "Cloudy",
    "10011": "Cloudy",
    "1100": "Mostly Clear",
    "11000": "Mostly Clear",
    "11001": "Mostly Clear",
    "1101": "Partly Cloudy",
    "11010": "Partly Cloudy",
    "11011": "Partly Cloudy",
    "1102": "Mostly Cloudy",
    "11020": "Mostly Cloudy",
    "11021": "Mostly Cloudy",
    "1103": "Partly Cloudy and Mostly Clear",
    "11030": "Partly Cloudy and Mostly Clear",
    "11031": "Partly Cloudy and Mostly Clear",
    "2000": "Fog",
    "20000": "Fog",
    "20001": "Fog",
    "2100": "Light Fog",
    "21000": "Light Fog",
    "21001": "Light Fog",
    "2101": "Mostly Clear and Light Fog",
    "21010": "Mostly Clear and Light Fog",
    "21011": "Mostly Clear and Light Fog",
    "2102": "Partly Cloudy and Light Fog",
    "21020": "Partly Cloudy and Light Fog",
    "21021": "Partly Cloudy and Light Fog",
    "2103": "Mostly Cloudy and Light Fog",
    "21030": "Mostly Cloudy and Light Fog",
    "21031": "Mostly Cloudy and Light Fog",
    "2106": "Mostly Clear and Fog",
    "21060": "Mostly Clear and Fog",
    "21061": "Mostly Clear and Fog",
    "2107": "Partly Cloudy and Fog",
    "21070": "Partly Cloudy and Fog",
    "21071": "Partly Cloudy and Fog",
    "2108": "Mostly Cloudy and Fog",
    "21080": "Mostly Cloudy and Fog",
    "21081": "Mostly Cloudy and Fog",
    "4000": "Drizzle",
    "40000": "Drizzle",
    "40001": "Drizzle",
    "4001": "Rain",
    "40010": "Rain",
    "40011": "Rain",
    "4200": "Light Rain",
    "42000": "Light Rain",
    "42001": "Light Rain",
    "4201": "Heavy Rain",
    "42010": "Heavy Rain",
    "42011": "Heavy Rain",
    "4202": "Partly Cloudy and Heavy Rain",
    "42020": "Partly Cloudy and Heavy Rain",
    "42021": "Partly Cloudy and Heavy Rain",
    "4203": "Mostly Clear and Drizzle",
    "42030": "Mostly Clear and Drizzle",
    "42031": "Mostly Clear and Drizzle",
    "4204": "Partly Cloudy and Drizzle",
    "42040": "Partly Cloudy and Drizzle",
    "42041": "Partly Cloudy and Drizzle",
    "4205": "Mostly Cloudy and Drizzle",
    "42050": "Mostly Cloudy and Drizzle",
    "42051": "Mostly Cloudy and Drizzle",
    "4208": "Partly Cloudy and Rain",
    "42080": "Partly Cloudy and Rain",
    "42081": "Partly Cloudy and Rain",
    "4209": "Mostly Clear and Rain",
    "42090": "Mostly Clear and Rain",
    "4210": "Mostly Cloudy and Rain",
    "42100": "Mostly Cloudy and Rain",
    "4211": "Mostly Clear and Heavy Rain",
    "42110": "Mostly Clear and Heavy Rain",
    "42111": "Mostly Clear and Heavy Rain",
    "4212": "Mostly Cloudy and Heavy Rain",
    "42120": "Mostly Cloudy and Heavy Rain",
    "42121": "Mostly Cloudy and Heavy Rain",
    "4213": "Mostly Clear and Light Rain",
    "42130": "Mostly Clear and Light Rain",
    "42131": "Mostly Clear and Light Rain",
    "4214": "Partly Cloudy and Light Rain",
    "42140": "Partly Cloudy and Light Rain",
    "42141": "Partly Cloudy and Light Rain",
    "4215": "Mostly Cloudy and Light Rain",
    "42150": "Mostly Cloudy and Light Rain",
    "42151": "Mostly Cloudy and Light Rain",
    "5000": "Snow",
    "50000": "Snow",
    "50001": "Snow",
    "5001": "Flurries",
    "50010": "Flurries",
    "50011": "Flurries",
    "5100": "Light Snow",
    "51000": "Light Snow",
    "51001": "Light Snow",
    "5101": "Heavy Snow",
    "51010": "Heavy Snow",
    "51011": "Heavy Snow",
    "5102": "Mostly Clear and Light Snow",
    "51020": "Mostly Clear and Light Snow",
    "51021": "Mostly Clear and Light Snow",
    "5103": "Partly Cloudy and Light Snow",
    "51030": "Partly Cloudy and Light Snow",
    "51031": "Partly Cloudy and Light Snow",
    "5104": "Mostly Cloudy and Light Snow",
    "51040": "Mostly Cloudy and Light Snow",
    "51041": "Mostly Cloudy and Light Snow",
    "5105": "Mostly Clear and Snow",
    "51050": "Mostly Clear and Snow",
    "51051": "Mostly Clear and Snow",
    "5106": "Partly Cloudy and Snow",
    "51060": "Partly Cloudy and Snow",
    "51061": "Partly Cloudy and Snow",
    "5107": "Mostly Cloudy and Snow",
    "51070": "Mostly Cloudy and Snow",
    "51071": "Mostly Cloudy and Snow",
    "5108": "Rain and Snow",
    "51080": "Rain and Snow",
    "51081": "Rain and Snow",
    "5110": "Drizzle and Snow",
    "51100": "Drizzle and Snow",
    "51101": "Drizzle and Snow",
    "5112": "Snow and Ice Pellets",
    "51120": "Snow and Ice Pellets",
    "51121": "Snow and Ice Pellets",
    "5114": "Snow and Freezing Rain",
    "51140": "Snow and Freezing Rain",
    "51141": "Snow and Freezing Rain",
    "5115": "Mostly Clear and Flurries",
    "51150": "Mostly Clear and Flurries",
    "51151": "Mostly Clear and Flurries",
    "5116": "Partly Cloudy and Flurries",
    "51160": "Partly Cloudy and Flurries",
    "51161": "Partly Cloudy and Flurries",
    "5117": "Mostly Cloudy and Flurries",
    "51170": "Mostly Cloudy and Flurries",
    "51171": "Mostly Cloudy and Flurries",
    "5119": "Mostly Clear and Heavy Snow",
    "51190": "Mostly Clear and Heavy Snow",
    "51191": "Mostly Clear and Heavy Snow",
    "5120": "Partly Cloudy and Heavy Snow",
    "51200": "Partly Cloudy and Heavy Snow",
    "51201": "Partly Cloudy and Heavy Snow",
    "5121": "Mostly Cloudy and Heavy Snow",
    "51210": "Mostly Cloudy and Heavy Snow",
    "51211": "Mostly Cloudy and Heavy Snow",
    "6000": "Freezing Drizzle",
    "60000": "Freezing Drizzle",
    "60001": "Freezing Drizzle",
    "6001": "Freezing Rain",
    "60010": "Freezing Rain",
    "60011": "Freezing Rain",
    "6002": "Partly Cloudy and Freezing drizzle",
    "60020": "Partly Cloudy and Freezing drizzle",
    "60021": "Partly Cloudy and Freezing drizzle",
    "6003": "Mostly Clear and Freezing drizzle",
    "60030": "Mostly Clear and Freezing drizzle",
    "60031": "Mostly Clear and Freezing drizzle",
    "6004": "Mostly Cloudy and Freezing drizzle",
    "60040": "Mostly Cloudy and Freezing drizzle",
    "60041": "Mostly Cloudy and Freezing drizzle",
    "6200": "Light Freezing Rain",
    "62000": "Light Freezing Rain",
    "62001": "Light Freezing Rain",
    "6201": "Heavy Freezing Rain",
    "62010": "Heavy Freezing Rain",
    "62011": "Heavy Freezing Rain",
    "6202": "Partly Cloudy and Heavy Freezing Rain",
    "62020": "Partly Cloudy and Heavy Freezing Rain",
    "62021": "Partly Cloudy and Heavy Freezing Rain",
    "6203": "Partly Cloudy and Light Freezing Rain",
    "62030": "Partly Cloudy and Light Freezing Rain",
    "62031": "Partly Cloudy and Light Freezing Rain",
    "6204": "Drizzle and Freezing Drizzle",
    "62040": "Drizzle and Freezing Drizzle",
    "62041": "Drizzle and Freezing Drizzle",
    "6205": "Mostly Clear and Light Freezing Rain",
    "62050": "Mostly Clear and Light Freezing Rain",
    "62051": "Mostly Clear and Light Freezing Rain",
    "6206": "Light Rain and Freezing Drizzle",
    "62060": "Light Rain and Freezing Drizzle",
    "62061": "Light Rain and Freezing Drizzle",
    "6207": "Mostly Clear and Heavy Freezing Rain",
    "62070": "Mostly Clear and Heavy Freezing Rain",
    "62071": "Mostly Clear and Heavy Freezing Rain",
    "6208": "Mostly Cloudy and Heavy Freezing Rain",
    "62080": "Mostly Cloudy and Heavy Freezing Rain",
    "62081": "Mostly Cloudy and Heavy Freezing Rain",
    "6209": "Mostly Cloudy and Light Freezing Rain",
    "62090": "Mostly Cloudy and Light Freezing Rain",
    "62091": "Mostly Cloudy and Light Freezing Rain",
    "6212": "Drizzle and Freezing Rain",
    "62120": "Drizzle and Freezing Rain",
    "62121": "Drizzle and Freezing Rain",
    "6213": "Mostly Clear and Freezing Rain",
    "62130": "Mostly Clear and Freezing Rain",
    "62131": "Mostly Clear and Freezing Rain",
    "6214": "Partly Cloudy and Freezing Rain",
    "62140": "Partly Cloudy and Freezing Rain",
    "62141": "Partly Cloudy and Freezing Rain",
    "6215": "Mostly Cloudy and Freezing Rain",
    "62150": "Mostly Cloudy and Freezing Rain",
    "62151": "Mostly Cloudy and Freezing Rain",
    "6220": "Light Rain and Freezing Rain",
    "62200": "Light Rain and Freezing Rain",
    "62201": "Light Rain and Freezing Rain",
    "6222": "Rain and Freezing Rain",
    "62220": "Rain and Freezing Rain",
    "62221": "Rain and Freezing Rain",
    "7000": "Ice Pellets",
    "70000": "Ice Pellets",
    "70001": "Ice Pellets",
    "7101": "Heavy Ice Pellets",
    "71010": "Heavy Ice Pellets",
    "71011": "Heavy Ice Pellets",
    "7102": "Light Ice Pellets",
    "71020": "Light Ice Pellets",
    "71021": "Light Ice Pellets",
    "7103": "Freezing Rain and Heavy Ice Pellets",
    "71030": "Freezing Rain and Heavy Ice Pellets",
    "71031": "Freezing Rain and Heavy Ice Pellets",
    "7105": "Drizzle and Ice Pellets",
    "71050": "Drizzle and Ice Pellets",
    "71051": "Drizzle and Ice Pellets",
    "7106": "Freezing Rain and Ice Pellets",
    "71060": "Freezing Rain and Ice Pellets",
    "71061": "Freezing Rain and Ice Pellets",
    "7107": "Partly Cloudy and Ice Pellets",
    "71070": "Partly Cloudy and Ice Pellets",
    "71071": "Partly Cloudy and Ice Pellets",
    "7108": "Mostly Clear and Ice Pellets",
    "71080": "Mostly Clear and Ice Pellets",
    "71081": "Mostly Clear and Ice Pellets",
    "7109": "Mostly Cloudy and Ice Pellets",
    "71090": "Mostly Cloudy and Ice Pellets",
    "71091": "Mostly Cloudy and Ice Pellets",
    "7110": "Mostly Clear and Light Ice Pellets",
    "71100": "Mostly Clear and Light Ice Pellets",
    "71101": "Mostly Clear and Light Ice Pellets",
    "7111": "Partly Cloudy and Light Ice Pellets",
    "71110": "Partly Cloudy and Light Ice Pellets",
    "71111": "Partly Cloudy and Light Ice Pellets",
    "7112": "Mostly Cloudy and Light Ice Pellets",
    "71120": "Mostly Cloudy and Light Ice Pellets",
    "71121": "Mostly Cloudy and Light Ice Pellets",
    "7113": "Mostly Clear and Heavy Ice Pellets",
    "71130": "Mostly Clear and Heavy Ice Pellets",
    "71131": "Mostly Clear and Heavy Ice Pellets",
    "7114": "Partly Cloudy and Heavy Ice Pellets",
    "71140": "Partly Cloudy and Heavy Ice Pellets",
    "71141": "Partly Cloudy and Heavy Ice Pellets",
    "7116": "Mostly Cloudy and Heavy Ice Pellets",
    "71160": "Mostly Cloudy and Heavy Ice Pellets",
    "71161": "Mostly Cloudy and Heavy Ice Pellets",
    "8000": "Thunderstorm",
    "80000": "Thunderstorm",
    "80001": "Thunderstorm",
    "8001": "Mostly Clear and Thunderstorm",
    "80010": "Mostly Clear and Thunderstorm",
    "80011": "Mostly Clear and Thunderstorm",
    "8002": "Mostly Cloudy and Thunderstorm",
    "80020": "Mostly Cloudy and Thunderstorm",
    "80021": "Mostly Cloudy and Thunderstorm",
    "8003": "Partly Cloudy and Thunderstorm",
    "80030": "Partly Cloudy and Thunderstorm",
    "80031": "Partly Cloudy and Thunderstorm"
}

weather_code_to_icon_mapping = {
    "10000": "10000_clear_large@2x.png",
    "10001": "10001_clear_large@2x.png",
    "10010": "10010_cloudy_large@2x.png",
    "10011": "10010_cloudy_large@2x.png",
    "11000": "11000_mostly_clear_large@2x.png",
    "11001": "11001_mostly_clear_large@2x.png",
    "11010": "11010_partly_cloudy_large@2x.png",
    "11011": "11011_partly_cloudy_large@2x.png",
    "11020": "11020_mostly_cloudy_large@2x.png",
    "11021": "11021_mostly_cloudy_large@2x.png",
    "11030": "11030_mostly_clear_large@2x.png",
    "11031": "11031_mostly_clear_large@2x.png",
    "20000": "20000_fog_large@2x.png",
    "21000": "21000_fog_light_large@2x.png",
    "21010": "21010_fog_light_mostly_clear_large@2x.png",
    "21011": "21011_fog_light_mostly_clear_large@2x.png",
    "21020": "21020_fog_light_partly_cloudy_large@2x.png",
    "21021": "21021_fog_light_partly_cloudy_large@2x.png",
    "21030": "21030_fog_light_mostly_cloudy_large@2x.png",
    "21031": "21031_fog_light_mostly_cloudy_large@2x.png",
    "21060": "21060_fog_mostly_clear_large@2x.png",
    "21061": "21061_fog_mostly_clear_large@2x.png",
    "21070": "21070_fog_partly_cloudy_large@2x.png",
    "21071": "21071_fog_partly_cloudy_large@2x.png",
    "21080": "21080_fog_mostly_cloudy_large@2x.png",
    "21081": "21081_fog_mostly_cloudy_large@2x.png",
    "40000": "40000_drizzle_large@2x.png",
    "40010": "40010_rain_large@2x.png",
    "42000": "42000_rain_light_large@2x.png",
    "42010": "42010_rain_heavy_large@2x.png",
    "42020": "42020_rain_heavy_partly_cloudy_large@2x.png",
    "42021": "42021_rain_heavy_partly_cloudy_large@2x.png",
    "42030": "42030_drizzle_mostly_clear_large@2x.png",
    "42031": "42031_drizzle_mostly_clear_large@2x.png",
    "42040": "42040_drizzle_partly_cloudy_large@2x.png",
    "42041": "42041_drizzle_partly_cloudy_large@2x.png",
    "42050": "42050_drizzle_mostly_cloudy_large@2x.png",
    "42051": "42051_drizzle_mostly_cloudy_large@2x.png",
    "42080": "42080_rain_partly_cloudy_large@2x.png",
    "42081": "42081_rain_partly_cloudy_large@2x.png",
    "42090": "42090_rain_mostly_clear_large@2x.png",
    "42091": "42091_rain_mostly_clear_large@2x.png",
    "42100": "42100_rain_mostly_cloudy_large@2x.png",
    "42101": "42101_rain_mostly_cloudy_large@2x.png",
    "42110": "42110_rain_heavy_mostly_clear_large@2x.png",
    "42111": "42111_rain_heavy_mostly_clear_large@2x.png",
    "42120": "42120_rain_heavy_mostly_cloudy_large@2x.png",
    "42121": "42121_rain_heavy_mostly_cloudy_large@2x.png",
    "42130": "42130_rain_light_mostly_clear_large@2x.png",
    "42131": "42131_rain_light_mostly_clear_large@2x.png",
    "42140": "42140_rain_light_partly_cloudy_large@2x.png",
    "42141": "42141_rain_light_partly_cloudy_large@2x.png",
    "42150": "42150_rain_light_mostly_cloudy_large@2x.png",
    "42151": "42151_rain_light_mostly_cloudy_large@2x.png",
    "50000": "50000_snow_large@2x.png",
    "50010": "50010_flurries_large@2x.png",
    "51000": "51000_snow_light_large@2x.png",
    "51010": "51010_snow_heavy_large@2x.png",
    "51020": "51020_snow_light_mostly_clear_large@2x.png",
    "51021": "51021_snow_light_mostly_clear_large@2x.png",
    "51030": "51030_snow_light_partly_cloudy_large@2x.png",
    "51031": "51031_snow_light_partly_cloudy_large@2x.png",
    "51040": "51040_snow_light_mostly_cloudy_large@2x.png",
    "51041": "51041_snow_light_mostly_cloudy_large@2x.png",
    "51050": "51050_snow_mostly_clear_large@2x.png",
    "51051": "51051_snow_mostly_clear_large@2x.png",
    "51060": "51060_snow_partly_cloudy_large@2x.png",
    "51061": "51061_snow_partly_cloudy_large@2x.png",
    "51070": "51070_snow_mostly_cloudy_large@2x.png",
    "51071": "51071_snow_mostly_cloudy_large@2x.png",
    "51080": "51080_wintry_mix_large@2x.png",
    "51100": "51100_wintry_mix_large@2x.png",
    "51120": "51120_wintry_mix_large@2x.png",
    "51140": "51140_wintry_mix_large@2x.png",
    "51150": "51150_flurries_mostly_clear_large@2x.png",
    "51151": "51151_flurries_mostly_clear_large@2x.png",
    "51160": "51160_flurries_partly_cloudy_large@2x.png",
    "51161": "51161_flurries_partly_cloudy_large@2x.png",
    "51170": "51170_flurries_mostly_cloudy_large@2x.png",
    "51171": "51171_flurries_mostly_cloudy_large@2x.png",
    "51190": "51190_snow_heavy_mostly_clear_large@2x.png",
    "51191": "51191_snow_heavy_mostly_clear_large@2x.png",
    "51200": "51200_snow_heavy_partly_cloudy_large@2x.png",
    "51201": "51201_snow_heavy_partly_cloudy_large@2x.png",
    "51210": "51210_snow_heavy_mostly_cloudy_large@2x.png",
    "51211": "51211_snow_heavy_mostly_cloudy_large@2x.png",
    "51220": "51220_wintry_mix_large@2x.png",
    "60000": "60000_freezing_rain_drizzle_large@2x.png",
    "60010": "60010_freezing_rain_large@2x.png",
    "60020": "60020_freezing_rain_drizzle_partly_cloudy_large@2x.png",
    "60021": "60021_freezing_rain_drizzle_partly_cloudy_large@2x.png",
    "60030": "60030_freezing_rain_drizzle_mostly_clear_large@2x.png",
    "60031": "60031_freezing_rain_drizzle_mostly_clear_large@2x.png",
    "60040": "60040_freezing_rain_drizzle_mostly_cloudy_large@2x.png",
    "60041": "60041_freezing_rain_drizzle_mostly_cloudy_large@2x.png",
    "62000": "62000_freezing_rain_light_large@2x.png",
    "62010": "62010_freezing_rain_heavy_large@2x.png",
    "62020": "62020_freezing_rain_heavy_partly_cloudy_large@2x.png",
    "62021": "62021_freezing_rain_heavy_partly_cloudy_large@2x.png",
    "62030": "62030_freezing_rain_light_partly_cloudy_large@2x.png",
    "62031": "62031_freezing_rain_light_partly_cloudy_large@2x.png",
    "62040": "62040_wintry_mix_large@2x.png",
    "62050": "62050_freezing_rain_light_mostly_clear_large@2x.png",
    "62051": "62051_freezing_rain_light_mostly_clear_large@2x.png",
    "62060": "62060_wintry_mix_large@2x.png",
    "62070": "62070_freezing_rain_heavy_mostly_clear_large@2x.png",
    "62071": "62071_freezing_rain_heavy_mostly_clear_large@2x.png",
    "62080": "62080_freezing_rain_heavy_mostly_cloudy_large@2x.png",
    "62081": "62081_freezing_rain_heavy_mostly_cloudy_large@2x.png",
    "62090": "62090_freezing_rain_light_mostly_cloudy_large@2x.png",
    "62091": "62091_freezing_rain_light_mostly_cloudy_large@2x.png",
    "62120": "62120_wintry_mix_large@2x.png",
    "62130": "62130_freezing_rain_mostly_clear_large@2x.png",
    "62131": "62131_freezing_rain_mostly_clear_large@2x.png",
    "62140": "62140_freezing_rain_partly_cloudy_large@2x.png",
    "62141": "62141_freezing_rain_partly_cloudy_large@2x.png",
    "62150": "62150_freezing_rain_mostly_cloudy_large@2x.png",
    "62151": "62151_freezing_rain_mostly_cloudy_large@2x.png",
    "62200": "62200_wintry_mix_large@2x.png",
    "62220": "62220_wintry_mix_large@2x.png",
    "70000": "70000_ice_pellets_large@2x.png",
    "71010": "71010_ice_pellets_heavy_large@2x.png",
    "71020": "71020_ice_pellets_light_large@2x.png",
    "71030": "71030_wintry_mix_large@2x.png",
    "71050": "71050_wintry_mix_large@2x.png",
    "71060": "71060_wintry_mix_large@2x.png",
    "71070": "71070_ice_pellets_partly_cloudy_large@2x.png",
    "71071": "71071_ice_pellets_partly_cloudy_large@2x.png",
    "71080": "71080_ice_pellets_mostly_clear_large@2x.png",
    "71081": "71081_ice_pellets_mostly_clear_large@2x.png",
    "71090": "71090_ice_pellets_mostly_cloudy_large@2x.png",
    "71091": "71091_ice_pellets_mostly_cloudy_large@2x.png",
    "71100": "71100_ice_pellets_light_mostly_clear_large@2x.png",
    "71101": "71101_ice_pellets_light_mostly_clear_large@2x.png",
    "71110": "71110_ice_pellets_light_partly_cloudy_large@2x.png",
    "71111": "71111_ice_pellets_light_partly_cloudy_large@2x.png",
    "71120": "71120_ice_pellets_light_mostly_cloudy_large@2x.png",
    "71121": "71121_ice_pellets_light_mostly_cloudy_large@2x.png",
    "71130": "71130_ice_pellets_heavy_mostly_clear_large@2x.png",
    "71131": "71131_ice_pellets_heavy_mostly_clear_large@2x.png",
    "71140": "71140_ice_pellets_heavy_partly_cloudy_large@2x.png",
    "71141": "71141_ice_pellets_heavy_partly_cloudy_large@2x.png",
    "71150": "71150_wintry_mix_large@2x.png",
    "71160": "71160_ice_pellets_heavy_mostly_cloudy_large@2x.png",
    "71161": "71161_ice_pellets_heavy_mostly_cloudy_large@2x.png",
    "71170": "71170_wintry_mix_large@2x.png",
    "80000": "80000_tstorm_large@2x.png",
    "80010": "80010_tstorm_mostly_clear_large@2x.png",
    "80011": "80011_tstorm_mostly_clear_large@2x.png",
    "80020": "80020_tstorm_mostly_cloudy_large@2x.png",
    "80021": "80021_tstorm_mostly_cloudy_large@2x.png",
    "80030": "80030_tstorm_partly_cloudy_large@2x.png",
    "80031": "80031_tstorm_partly_cloudy_large@2x.png"
}
