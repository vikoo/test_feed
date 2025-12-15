import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

from cron.data_upload.f1.f1_utils import fetch_race_results_table, practice_1, practice_2, practice_3, qualifying, \
    sprint_qualifying, main_race, sprint_race, fastest_laps, get_position, get_laps, get_race_result_time_dnf, POSITION, \
    TIME, DRIVERNUM, SEASONGRID, RACE, POINTS, LAPS, get_race_points, DRIVERNAME, get_quali_common_elements


def fetch_race_results(f1_url, season_grid_map, race_id, race_type, year, q2_id, q1_id):
    table_rows = fetch_race_results_table(f1_url)
    json_rows = {}
    if race_type in (practice_1, practice_2, practice_3):
        print(f"Practice session results found. ")
        json_rows = fetch_practice_rows(table_rows, race_id, season_grid_map)
        return json_rows
    elif race_type in (qualifying, sprint_qualifying):
        json_rows = fetch_quali_rows(table_rows, race_id, race_type, season_grid_map, q2_id, q1_id)
        print(f"Qualifying session results found.")
    elif race_type in (main_race, sprint_race):
        json_rows = fetch_race_result_rows(table_rows, race_id, race_type, season_grid_map)
        print(f"race/ sprint session results found.")
    elif race_type == fastest_laps:
        print(f"fastest laps results found.")

    return json_rows



def fetch_practice_rows(table_rows, race_id, season_grid_map):
    practice_rows = []
    previous_time = ""
    for index, row in enumerate(table_rows[1:], start=1):  # Skip header row
        cols = row.find_all("td")
        if len(cols) < 6:
            continue  # Skip rows that don't have enough columns
        position = get_position(cols[0].text.strip(), index)
        driver_id = cols[1].text.strip()
        driver_name = cols[2].text.strip()
        season_grid = season_grid_map.get(int(driver_id))
        laps = get_laps(cols[5].text)
        time_info = get_race_result_time_dnf(cols[4].text.strip(), previous_time)
        if not previous_time:
            previous_time = time_info[TIME]

        practice_row = {
            POSITION: position,
            DRIVERNUM: driver_id,
            SEASONGRID: season_grid,
            RACE: race_id,
            POINTS: 0,
            LAPS: laps,
            DRIVERNAME: driver_name
        }
        practice_row.update(time_info)
        print(f"practice_row: {practice_row}")
        # add the constructed row to the list
        practice_rows.append(practice_row)
    return practice_rows


def fetch_race_result_rows(table_rows, race_id, race_type, season_grid_map):
    race_rows = []
    previous_time = ""
    for index, row in enumerate(table_rows[1:], start=1):  # Skip header row
        cols = row.find_all("td")
        if len(cols) < 7:
            continue  # Skip rows that don't have enough columns
        position = get_position(cols[0].text.strip(), index)
        driver_num = cols[1].text.strip()
        driver_name = cols[2].text.strip()
        season_grid = season_grid_map.get(int(driver_num))
        laps = get_laps(cols[4].text)
        time_info = get_race_result_time_dnf(cols[5].text.strip(), previous_time)
        if not previous_time:
            previous_time = time_info[TIME]
        points = get_race_points(race_type, position)

        race_row = {
            POSITION: position,
            DRIVERNUM: driver_num,
            SEASONGRID: season_grid,
            RACE: race_id,
            POINTS: points,
            LAPS: laps,
            DRIVERNAME: driver_name
        }
        race_row.update(time_info)
        print(f"practice_row: {race_row}")
        # add the constructed row to the list
        race_rows.append(race_row)
    return race_rows

def fetch_quali_rows(row_elements, race_id, race_type, season_grid_map, q2_id, q1_id):
    rows = []
    print(
        f"getRaceQualiRows: Q3 Id: {race_id}, "
        f"Q2 id: {q2_id}, Q1 Id: {q1_id}"
    )

    rows = []

    # ---------------- Q1 ----------------
    for r in range(1, len(row_elements)):
        cols = row_elements[r].find_all("td")

        if len(cols) < 3:
            continue

        data = get_quali_common_elements(
            cols, q1_id, 4, r, season_grid_map
        )

        if r == 1 and data.get(TIME) == "":
            print("clearing data as first row does not have time for Q1")
            rows.clear()
            break

        print(data)
        rows.append(data)

    # ---------------- Q2 ----------------
    for r in range(1, len(row_elements) - 5):
        cols = row_elements[r].find_all("td")

        if len(cols) < 3:
            continue

        data = get_quali_common_elements(
            cols, q2_id, 5, r, season_grid_map
        )

        if r == 1 and data.get(TIME) == "":
            print("clearing data as first row does not have time for Q2")
            rows.clear()
            break

        print(data)
        rows.append(data)

    # ---------------- Q3 ----------------
    for r in range(1, len(row_elements)):
        cols = row_elements[r].find_all("td")

        if len(cols) < 3:
            continue

        data = get_quali_common_elements(
            cols, race_id, 6, r, season_grid_map
        )

        if r == 1 and data.get(TIME) == "":
            print("clearing data as first row does not have time for Q3")
            rows.clear()
            break

        print(data)
        rows.append(data)

    return rows