from cron.strapi_api.apis import get_upcoming_races, update_weather, create_weather, update_weather_in_race
from cron.weather.weather_utils import *
from loguru import logger

# Load environment variables from .env file - this is for local setup of token
load_dotenv()

def load_grand_prix(is_for_f1: bool) :
    # read grand prix data from saved file
    json_data = read_grand_prix_json(is_for_f1)

    # is json is empty then fetch it from server and save it to local file
    if not json_data:
        logger.warning("JSON is empty")
        json_data = get_upcoming_races(is_for_f1)
        save_grandprix_json(json_data, is_for_f1)

    # if json is outdated then fetch it from server and save it
    is_gp_update_required = check_json_outdated(json_data)
    if is_gp_update_required:
        json_data = get_upcoming_races(is_for_f1)
        save_grandprix_json(json_data, is_for_f1)

    # now get the lat, long for the location and fetch the weather
    latitude, longitude = get_track_coordinates(json_data)
    logger.info(f"Latitude: {latitude}")
    logger.info(f"Longitude: {longitude}")

    if latitude is not None and longitude is not None:
        races = get_races_from_json(json_data)
        logger.debug(f"races: {races}")

        # check for any ongoing event
        is_any_ongoing_event = False
        for race in races:
            start_time = race.get("attributes", {}).get("startTime")
            race_type = race.get("attributes", {}).get("type")
            is_any_ongoing_event = is_race_time_in_now_window(start_time)
            logger.info(f"type: {race_type} - time: {start_time} - is ongoing event: {is_any_ongoing_event}")

        # if any ongoing event then need to fetch current weather with hourly weather
        current_weather = {}
        hourly_weather = {}
        if is_any_ongoing_event:
            current_weather = fetch_current_weather(latitude, longitude)
            logger.info(f"CURRENT WEATHER: {current_weather}")
        else :
            hourly_weather = fetch_hourly_weather(latitude, longitude)
            logger.info("HOURLY WEATHER: fetched")

        for race in races:
            start_time = race.get("attributes", {}).get("startTime")
            race_type = race.get("attributes", {}).get("type")
            race_id = race.get("id")
            is_any_ongoing_event = is_race_time_in_now_window(start_time)

            logger.info(f"id: {race_id}, type: {race_type} - time: {start_time} - is ongoing event: {is_any_ongoing_event}")

            if is_any_ongoing_event:
                weather_obj = get_current_weather_from_json(current_weather)
                if weather_obj:
                    logger.debug(f"current weather time: {weather_obj['time']}")
                    logger.debug(f"Temperature: {weather_obj['values']['temperature']}")
                else:
                    logger.warning("No weather data available")

            else:
                logger.debug(f"weather: start time {start_time}")
                weather_obj = get_weather_for_time(hourly_weather, start_time)
                logger.debug(f"weather: {weather_obj}")
                if weather_obj:
                    logger.debug(f"Closest weather time: {weather_obj['time']}")
                    logger.debug(f"Temperature: {weather_obj['values']['temperature']}")
                else:
                    logger.warning("No weather data available")

            if weather_obj:
                logger.debug(f"weather obj: {weather_obj}")
                # get weather data from race
                weather_data_in_race = race.get("attributes", {}).get("weather", {}).get("data")
                if weather_data_in_race:
                    # update the data in existing weather object in strapi
                    logger.info("updating the weather entry in strapi")
                    update_weather(is_for_f1, weather_data_in_race.get("id"), weather_obj, race_id, latitude, longitude)
                else:
                    # new entry of weather object in strapi
                    logger.info("creating the new weather entry in strapi")
                    weather_id = create_weather(is_for_f1, weather_obj, race_id, latitude, longitude)
                    update_weather_in_race(is_for_f1, weather_id, race_id)
                    delete_grandprix_json_file(is_for_f1)


if __name__ == "__main__":
    logger.info("------------- FETCHING F1 Weather ------------------")
    load_grand_prix(is_for_f1=True)
    logger.info("------------- FETCHING Moto GP Weather ------------------")
    load_grand_prix(is_for_f1=False)
