from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup


practice_1 = "FP1"
practice_2 = "FP2"
practice_3 = "FP3"
qualifying_1 = "Q1"
qualifying_2 = "Q2"
qualifying = "Q3"
sprint_qualifying_1 = "SQ1"
sprint_qualifying_2 = "SQ2"
sprint_qualifying = "SQ3"
sprint_race = "Sprint"
main_race = "Race"
fastest_laps = "Fastest Laps"

DNF = "dnf"
TIME = "time"
POSITION = "position"
DRIVERNUM= "driverNumber"
SEASONGRID = "seasonGrid"
RACE = "race"
POINTS = "points"
LAPS = "laps"
DRIVERNAME = "driverName"


race_type_to_url_map = {
    practice_1: "practice/1",
    practice_2: "practice/2",
    practice_3: "practice/3",
    qualifying: "qualifying",
    sprint_qualifying: "sprint-qualifying",
    sprint_race: "sprint-results",
    main_race : "race-result",
    fastest_laps: "fastest-laps"
}

def fetch_race_results_table(url: str):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    response = requests.get(url, headers=headers)
    response.raise_for_status()  # raise error if request fails
    soup = BeautifulSoup(response.text, "html.parser")
    table = soup.find("table", class_="Table-module_table__cKsW2")
    rows = table.find_all("tr")
    # print (f"Fetched {rows} rows from the race results table.")
    return rows

def get_position(text: str, default: int = 1) -> int:
    try:
        return int(text)
    except ValueError:
        return default

def get_laps(text: str) -> int:
    try:
        return int(text)
    except ValueError:
        return 0

def get_race_result_time_dnf(time: str, previous_time: str) -> dict:
    print(f"time: {time}, previousTime: {previous_time}")

    data = {}

    if not previous_time:
        data[DNF] = False
        data[TIME] = time

    elif time == "DNF" or time == "+0 lap":
        data[DNF] = True
        data[TIME] = ""

    elif "lap" in time:
        # +1 lap, +2 laps, etc
        data[DNF] = False
        data[TIME] = ""

    elif "+" in time and "." in time and time.endswith("s"):
        data[DNF] = False
        seconds = time.replace("+", "").replace("s", "")
        data[TIME] = add_seconds_to_time(previous_time, float(seconds))

    else:
        data[DNF] = True
        data[TIME] = ""

    return data

def add_seconds_to_time(current_time: str, add_seconds: float) -> str:
    time_parts = current_time.split(":")

    if len(time_parts) == 3:
        # HH:MM:SS.mmm
        hours = int(time_parts[0])
        minutes = int(time_parts[1])

        seconds_part, milliseconds_part = time_parts[2].split(".")
        seconds = int(seconds_part)
        milliseconds = int(milliseconds_part)

        dt = datetime(1, 1, 1, hours, minutes, seconds, milliseconds * 1000)

        duration = timedelta(milliseconds=int(add_seconds * 1000))
        new_time = dt + duration

        formatted_time = (
            f"{new_time.hour}:"
            f"{new_time.minute:02d}:"
            f"{new_time.second:02d}."
            f"{new_time.microsecond // 1000:03d}"
        )

    else:
        # MM:SS.mmm
        minutes = int(time_parts[0])

        seconds_part, milliseconds_part = time_parts[1].split(".")
        seconds = int(seconds_part)
        milliseconds = int(milliseconds_part)

        dt = datetime(1, 1, 1, 0, minutes, seconds, milliseconds * 1000)

        duration = timedelta(milliseconds=int(add_seconds * 1000))
        new_time = dt + duration

        formatted_time = (
            f"{new_time.minute:02d}:"
            f"{new_time.second:02d}."
            f"{new_time.microsecond // 1000:03d}"
        )

    return formatted_time

def get_race_points(race_type, position) -> int:
    if race_type == main_race:
        return get_race_points_from_position(position)
    else :
        return get_race_points_from_position_sprint(position)

def get_race_points_from_position(position: int) -> int:
    points = {
        1: 25,
        2: 18,
        3: 15,
        4: 12,
        5: 10,
        6: 8,
        7: 6,
        8: 4,
        9: 2,
        10: 1,
    }
    return points.get(position, 0)


def get_race_points_from_position_sprint(position: int) -> int:
    points = {
        1: 8,
        2: 7,
        3: 6,
        4: 5,
        5: 4,
        6: 3,
        7: 2,
        8: 1,
    }
    return points.get(position, 0)

def get_quali_common_elements(
        cols,
        race_id: str,
        time_index: int,
        row: int,
        season_grid_map: dict[int, str],
):
    data = {}
    data[POINTS] = 0
    data[RACE] = race_id

    txt = cols[time_index].text.strip()
    data.update(get_race_time_and_dnf(txt))

    for i, col in enumerate(cols):
        txt = col.text.strip()

        if i == 0:
            data[POSITION] = int(
                get_race_position(txt, row)
            )

        elif i == 1:
            driver_id = int(txt)
            data[DRIVERNUM] = driver_id
            data[SEASONGRID] = season_grid_map.get(driver_id)

        elif i == 2:
            data[DRIVERNAME] = txt

        elif i == 7:
            data[LAPS] = int(txt)

    return data

def get_race_time_and_dnf(time: str) -> dict:
    data = {}

    if time == "DNF" or time == "+0 lap":
        data[DNF] = True
        data[TIME] = ""
    else:
        data[DNF] = False
        data[TIME] = time

    return data

def get_race_position(position: str, previous_position: int) -> str:
    try:
        return str(int(position))
    except (ValueError, TypeError):
        return str(previous_position)
