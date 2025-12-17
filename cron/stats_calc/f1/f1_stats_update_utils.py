from cron.strapi_api.apis import update_driver_standings, update_team_standings
import json

def update_stats(season, all_race_results, driver_standings, team_standings):
    print(f"## updateStats: {season}")

    driver_season_grid_id_to_stats_map = {}
    driver_multi_season_grid_id_to_stats_map = {}
    team_id_to_stats_map = {}

    standings_with_multiple_grids = []

    # --------------------------------------------------
    # DRIVER STATS
    # --------------------------------------------------

    for standing in driver_standings:

        standings_id = standing.get("id")
        if standings_id is None:
            continue

        season_grid = (
            standing.get("attributes", {})
            .get("seasonGrid", {})
            .get("data", {})
        )
        driver_season_grid_id = season_grid.get("id")

        race_results = [
            r for r in all_race_results
            if r.get("attributes", {})
               .get("seasonGrid", {})
               .get("data", {})
               .get("id") == driver_season_grid_id
        ]

        position = standing.get("attributes", {}).get("position", 0)

        driver_season_grid_id_to_stats_map[driver_season_grid_id] = populate_driver_data(
            standings_id,
            driver_season_grid_id,
            race_results,
            position
        )

        grids = (
            standing.get("attributes", {})
            .get("grids", {})
            .get("data", [])
        )

        if grids:
            grid_ids = [g.get("id") for g in grids]

            standings_with_multiple_grids.append((standing, grid_ids))

            for grid_id in grid_ids:
                if grid_id == driver_season_grid_id:
                    continue

                grid_race_results = [
                    r for r in all_race_results
                    if r.get("attributes", {})
                       .get("seasonGrid", {})
                       .get("data", {})
                       .get("id") == grid_id
                ]

                driver_season_grid_id_to_stats_map[grid_id] = populate_driver_data(
                    standings_id,
                    grid_id,
                    grid_race_results,
                    position,
                    is_primary_grid_id=False
                )

    # --------------------------------------------------
    # MERGED MULTI-GRID DRIVER STATS
    # --------------------------------------------------

    for standing, grid_ids in standings_with_multiple_grids:

        merged_race_results = [
            r for r in all_race_results
            if r.get("attributes", {})
               .get("seasonGrid", {})
               .get("data", {})
               .get("id") in grid_ids
        ]

        stats = populate_driver_data(
            standing.get("id"),
            "",
            merged_race_results,
            standing.get("attributes", {}).get("position", 0),
            is_team=True
        )

        primary_grid_id = (
            standing.get("attributes", {})
            .get("seasonGrid", {})
            .get("data", {})
            .get("id")
        )

        driver_multi_season_grid_id_to_stats_map[primary_grid_id] = stats

    # --------------------------------------------------
    # FINAL DRIVER LIST + SORT + ASSIGN POSITIONS
    # --------------------------------------------------

    drivers_list = []
    for standing in driver_standings:
        grid_id = (
            standing.get("attributes", {})
            .get("seasonGrid", {})
            .get("data", {})
            .get("id")
        )

        stats = (
                driver_multi_season_grid_id_to_stats_map.get(grid_id)
                or driver_season_grid_id_to_stats_map.get(grid_id)
        )
        drivers_list.append(stats)

    drivers_list.sort(
        key=lambda x: (
            -x["points"],
            x["bestRaceFinish"],
            x["position"]
        )
    )

    # assign final ranking
    for i, driver in enumerate(drivers_list):
        driver["position"] = i + 1
        if driver.get('is_primary_grid_id') is True:
            print(f"uploading for primary grid id: {driver.get('driver_season_grid_id')}")
            print(f"########################################################")
            print(f"driver: {driver}")
            # update_driver_standings(is_f1_feed=True, json_str=json.dumps(driver), row_id=driver.get("standings_id"))
        else:
            print(f"skip upload for non primary grid id: {driver.get('driver_season_grid_id')}")


    # --------------------------------------------------
    # TEAM STANDINGS
    # --------------------------------------------------

    for standing in team_standings:
        team_id = standing.get("id")

        grids = standing.get("attributes", {}).get("seasonGrid", {}).get("data", [])
        grid_ids = [g.get("id") for g in grids]
        avg_points_per_race = 0.0
        avg_points_per_sprint = 0.0
        driver_id_list = []

        for season_grid in (grids or []):
            driver_id_list.append(season_grid["id"])
            stats_map = driver_season_grid_id_to_stats_map.get(season_grid["id"])

            if stats_map is None:
                print(
                    f"********** driverMap: null for {season_grid['id']} : team: "
                    f"{standing['attributes']['chassis']['data']['attributes']['name']}"
                )
                continue

            avg_points_per_race += stats_map.get("avgPointsPerRace", 0)
            avg_points_per_sprint += stats_map.get("avgPointsPerSprint", 0)

        team_race_results = [
            r for r in all_race_results
            if r.get("attributes", {})
               .get("seasonGrid", {})
               .get("data", {})
               .get("id") in grid_ids
        ]

        position = standing.get("attributes", {}).get("position", 0)

        stats = populate_driver_data(
            team_id,
            "",
            team_race_results,
            position,
            is_team=True
        )

        team_id_to_stats_map[team_id] = stats
        team_id_to_stats_map[team_id]["avgPointsPerRace"] = avg_points_per_race
        team_id_to_stats_map[team_id]["avgPointsPerSprint"] = avg_points_per_sprint

    teams_list = list(team_id_to_stats_map.values())

    teams_list.sort(
        key=lambda x: (
            -x["points"],
            x["bestRaceFinish"],
            x["position"]
        )
    )

    for i, team in enumerate(teams_list):
        team["position"] = i + 1
        print(f"uploading for team standings id: {team.get('standings_id')}")
        print(f"########################################################")
        print(f"team: {team}")
        # update_team_standings(is_f1_feed=True, json_str=json.dumps(team), row_id=driver.get("standings_id"))


    return drivers_list, teams_list

def populate_driver_data(
        standing_id: str,
        driver_season_grid_id: str,
        race_results: list,
        position: int,
        is_team=False,
        is_primary_grid_id=True
):
    m = {}

    def get_val(obj, path, default=None):
        """safe nested lookup"""
        for key in path:
            if not isinstance(obj, dict) or key not in obj:
                return default
            obj = obj[key]
        return obj

    def race_list_of_type(rtype):
        return [
            r for r in race_results
            if get_val(r, ["attributes","race","data","attributes","type"]) == rtype
        ]

    def safe_int(v, default=0):
        try:
            return int(v)
        except:
            return default

    #
    # -------- populate race stats --------
    #
    def populate_race_data(
            rtype,
            points_key,
            avg_points_key,
            wins_key,
            podiums_key,
            top_finish_key,
            fl_key,
            dnf_key,
            best_finish_key,
            avg_finish_key,
            top_limit,
            top5_key=None
    ):
        races = race_list_of_type(rtype)

        m[points_key] = sum(safe_int(get_val(r, ["attributes","points"]), 0) for r in races)
        m[avg_points_key] = m[points_key] / len(races) if races else 0

        get_pos = lambda r: safe_int(get_val(r,["attributes","finalPos"]) or get_val(r,["attributes","position"]))

        m[wins_key] = sum(1 for r in races if get_pos(r) == 1)

        m[podiums_key] = sum(1 for r in races if 1 <= get_pos(r) <= 3)

        if top5_key:
            m[top5_key] = sum(1 for r in races if 1 <= get_pos(r) <= 5)

        m[top_finish_key] = sum(1 for r in races if 1 <= get_pos(r) <= top_limit)

        m[fl_key] = sum(1 for r in races if get_val(r, ["attributes","fastestLap"]) == True)

        m[dnf_key] = sum(
            1 for r in races
            if get_val(r, ["attributes","dnf"]) == True
            or get_val(r,["attributes","classification","data","attributes","type"]) is not None
        )

        positions = [get_pos(r) for r in races if get_pos(r) > 0]

        m[best_finish_key] = min(positions) if positions else 0
        m[avg_finish_key] = sum(positions)/len(races) if races and positions else -999


    #
    # 🏎 race aggregation
    #
    populate_race_data(
        "Race",
        "racePoints",
        "avgPointsPerRace",
        "raceWins",
        "racePodiums",
        "top10FinishInRace",
        "fastestLapsInRace",
        "dnfInRace",
        "bestRaceFinish",
        "avgRaceFinishPosition",
        10,
        "top5FinishInRace"
    )

    #
    # sprint aggregation
    #
    populate_race_data(
        "Sprint",
        "sprintPoints",
        "avgPointsPerSprint",
        "sprintWins",
        "sprintPodiums",
        "top8FinishInSprint",
        "fastestLapsInSprint",
        "dnfInSprint",
        "bestSprintFinish",
        "avgSprintFinishPosition",
        8
    )

    m["points"] = m["racePoints"] + m["sprintPoints"]


    #
    # -------- Qualifying stats --------
    #
    def populate_quali_data(
            qtype,
            pole_key,
            first_row_key,
            q3_key,
            best_key,
            avg_key,
            start_pos_key,
            gained_key,
            avg_finish_key
    ):
        qualis = race_list_of_type(qtype)
        get_pos = lambda r: safe_int(get_val(r,["attributes","finalPos"]) or get_val(r,["attributes","position"]))

        m[pole_key] = sum(1 for r in qualis if get_pos(r) == 1)
        m[first_row_key] = sum(1 for r in qualis if 1 <= get_pos(r) <= 2)

        m[q3_key] = sum(1 for r in qualis if get_val(r,["attributes","position"]) and get_pos(r) <= 10)

        positions = [safe_int(get_val(r,["attributes","position"])) for r in qualis if get_val(r,["attributes","position"])]

        m[best_key] = min(positions) if positions else 0
        m[avg_key] = sum(positions)/len(qualis) if positions else -999

        grid_positions = [get_pos(r) for r in qualis]
        m[start_pos_key] = sum(grid_positions)/len(qualis) if qualis else -999

        if m.get(avg_finish_key) == -999:
            m[gained_key] = -999
        else:
            m[gained_key] = m[start_pos_key] - m[avg_finish_key]


    populate_quali_data(
        "Q3",
        "racePoles",
        "raceFirstRowStarts",
        "q3Appearances",
        "bestQualiPos",
        "avgRaceQualiPosition",
        "avgRaceStartGridPosition",
        "avgRacePositionGained",
        "avgRaceFinishPosition"
    )

    populate_quali_data(
        "SQ3",
        "sprintPoles",
        "sprintFirstRowStarts",
        "sprintQ3Appearances",
        "bestSprintQualiPos",
        "avgSprintQualiPosition",
        "avgSprintStartGridPosition",
        "avgSprintPositionGained",
        "avgSprintFinishPosition"
    )


    #
    # count distinct GPs
    #
    gps = {
        get_val(r,["attributes","race","data","attributes","grandPrix","data","id"])
        for r in race_results
        if get_val(r,["attributes","race","data","attributes","grandPrix","data","id"])
    }
    m["noOfGPs"] = len(gps)

    #
    # final meta
    #
    m["standings_id"] = standing_id
    m["driver_season_grid_id"] = driver_season_grid_id
    m["is_primary_grid_id"] = is_primary_grid_id
    m["position"] = position

    return m

