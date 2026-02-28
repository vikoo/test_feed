import fastf1
import requests
from loguru import logger

if __name__ == "__main__":
    end_point = "https://api.formula1.com/v1/event-tracker"
    headers = {
        "apikey" : "BQ1SiSmLUOsp460VzXBlLrh689kGgYEZ",
        "Content-Type": "application/json",
        "locale":"en",
        "User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    }

    response = requests.get(url=end_point, headers=headers)
    logger.info(f"f1_live_data response: {response.json()}")
