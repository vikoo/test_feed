from cron.strapi_api.apis import update_driver_standings, update_team_standings

# MotoGP race type constants  (match the values stored in Strapi)
MOTO_RACE_RACE   = "Race"
MOTO_RACE_SPRINT = "Sprint"
MOTO_RACE_QUALI1 = "QNR1"
MOTO_RACE_QUALI2 = "QNR2"


def update_moto_gp_stats(season, all_race_results, driver_standings, team_standings):
    print(f"## updateStats: {season}")

    driver_season_grid_id_to_stats_map = {}
    driver_multi_season_grid_id_to_stats_map = {}
    team_id_to_stats_map = {}
    standings_with_multiple_grids = []

    # --------------------------------------------------
    # DRIVER STANDINGS
    # --------------------------------------------------
    for standing in driver_standings:
        standings_id = standing.get("id")
        if standings_id is None:
            print("## driverStanding: driver id null")
            continue

        driver_season_grid_id = (
            standing.get("attributes", {})
            .get("seasonGrid", {})
            .get("data", {})
            .get("id")
        )
        print(f"## standingsId: {standings_id} - driverSeasonGridId: {driver_season_grid_id}")
        position = standing.get("attributes", {}).get("position", 0)

        race_results = [
            r for r in all_race_results
            if _get_val(r, ["attributes", "seasonGrid", "data", "id"]) == driver_season_grid_id
        ]

        driver_season_grid_id_to_stats_map[driver_season_grid_id] = populate_moto_gp_driver_data(
            standings_id, driver_season_grid_id, race_results, position
        )

        # handle drivers who raced for multiple teams (multiple grids)
        grids = (
            standing.get("attributes", {})
            .get("grids", {})
            .get("data", [])
        )
        if grids:
            print(f"## standingsId: {standings_id} - driverSeasonGridId: {driver_season_grid_id} -> has multiple grids")
            grid_ids = [g.get("id") for g in grids]
            standings_with_multiple_grids.append((standing, grid_ids))

            for grid_id in grid_ids:
                if grid_id == driver_season_grid_id:
                    print(f"GRIDS primary driverStanding: gridId: {grid_id} NOT calculating data")
                    continue
                print(f"GRIDS member driverStanding: gridId: {grid_id}")
                grid_race_results = [
                    r for r in all_race_results
                    if _get_val(r, ["attributes", "seasonGrid", "data", "id"]) == grid_id
                ]
                driver_season_grid_id_to_stats_map[grid_id] = populate_moto_gp_driver_data(
                    standings_id, grid_id, grid_race_results, position, is_primary_grid_id=False
                )

    # --------------------------------------------------
    # MERGED MULTI-GRID DRIVER STATS
    # --------------------------------------------------
    if standings_with_multiple_grids:
        print(f"standingsWithMultipleGrids: {len(standings_with_multiple_grids)}")
        for standing, grid_ids in standings_with_multiple_grids:
            print(f"standingsWithMultipleGrids collecting for standingsId: {standing.get('id')}")
            print(f"standingsWithMultipleGrids gridIds: {grid_ids}")
            merged_race_results = [
                r for r in all_race_results
                if _get_val(r, ["attributes", "seasonGrid", "data", "id"]) in grid_ids
            ]
            stats = populate_moto_gp_driver_data(
                standing.get("id"), "", merged_race_results,
                standing.get("attributes", {}).get("position", 0), is_team=True
            )
            primary_grid_id = (
                standing.get("attributes", {})
                .get("seasonGrid", {})
                .get("data", {})
                .get("id")
            )
            driver_multi_season_grid_id_to_stats_map[primary_grid_id] = stats

    # --------------------------------------------------
    # SORT DRIVERS + ASSIGN POSITIONS + UPLOAD
    # --------------------------------------------------
    drivers_list = []
    for standing in driver_standings:
        grid_id = (
            standing.get("attributes", {})
            .get("seasonGrid", {})
            .get("data", {})
            .get("id")
        )
        if driver_multi_season_grid_id_to_stats_map.get(grid_id) is not None:
            print(f"adding multi GRIDS driverStanding to list: gridId: {grid_id}")
            drivers_list.append(driver_multi_season_grid_id_to_stats_map[grid_id])
        else:
            print(f"adding single driverStanding: gridId to list: gridId: {grid_id}")
            drivers_list.append(driver_season_grid_id_to_stats_map[grid_id])

    drivers_list.sort(
        key=lambda x: (
            -x["points"],
            x["bestRaceFinish"],
            x["position"]
        )
    )

    for i, driver in enumerate(drivers_list):
        driver["position"] = i + 1
        if driver.get("is_primary_grid_id") is True:
            print(f"uploading for primary grid id: {driver.get('driver_season_grid_id')}")
            print(f"########################################################")
            print(f"driver: {driver}")
            update_driver_standings(is_f1_feed=False, driver_map=driver, row_id=driver.get("standings_id"))
        else:
            print(f"skip upload for non primary grid id: {driver.get('driver_season_grid_id')}")

    # --------------------------------------------------
    # TEAM STANDINGS
    # --------------------------------------------------
    for standing in team_standings:
        team_id = standing.get("id")
        grids = standing.get("attributes", {}).get("seasonGrid", {}).get("data", [])
        grid_ids = [g.get("id") for g in grids]
        driver_id_list = []
        avg_points_per_race = 0.0
        avg_points_per_sprint = 0.0

        for season_grid in grids:
            grid_id = season_grid.get("id")
            driver_id_list.append(grid_id)
            stats_map = driver_season_grid_id_to_stats_map.get(grid_id)
            if stats_map is None:
                team_name = (
                    standing.get("attributes", {})
                    .get("chassis", {})
                    .get("data", {})
                    .get("attributes", {})
                    .get("name", "unknown")
                )
                print(f"********** driverMap: null for {grid_id} : team: {team_name}")
                continue
            avg_points_per_race  += stats_map.get("avgPointsPerRace", 0.0)
            avg_points_per_sprint += stats_map.get("avgPointsPerSprint", 0.0)

        team_race_results = [
            r for r in all_race_results
            if _get_val(r, ["attributes", "seasonGrid", "data", "id"]) in driver_id_list
        ]
        position = standing.get("attributes", {}).get("position", 0)

        stats = populate_moto_gp_driver_data(team_id, "", team_race_results, position, is_team=True)
        stats["avgPointsPerRace"]  = avg_points_per_race
        stats["avgPointsPerSprint"] = avg_points_per_sprint
        team_id_to_stats_map[team_id] = stats

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
        update_team_standings(is_f1_feed=False, team_map=team, row_id=team.get("standings_id"))

    return drivers_list, teams_list


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_val(obj, path, default=None):
    """Safe nested dict lookup via a list of keys."""
    for key in path:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(key, default)
        if obj is None:
            return default
    return obj


def _safe_float(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _safe_int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Core stats builder  (mirrors Dart populateDriverData)
# ---------------------------------------------------------------------------

def populate_moto_gp_driver_data(
        standing_id,
        driver_season_grid_id,
        race_results: list,
        position: int,
        is_team: bool = False,
        is_primary_grid_id: bool = True
) -> dict:
    """
    Build the stats dict for a driver (or team).
    Mirrors the Dart populateDriverData() in moto_gp_stats.dart.
    """
    m = {}

    def race_list_of_type(rtype):
        return [
            r for r in race_results
            if _get_val(r, ["attributes", "race", "data", "attributes", "type"]) == rtype
        ]

    def effective_pos(r):
        """finalPos takes precedence over position (same as Dart finalPos ?? position)."""
        fp = _get_val(r, ["attributes", "finalPos"])
        if fp is not None:
            return _safe_int(fp)
        return _safe_int(_get_val(r, ["attributes", "position"]))

    # ------------------------------------------------------------------ #
    #  populate_race_data  –  Race / Sprint aggregation                    #
    # ------------------------------------------------------------------ #
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

        m[points_key]     = sum(_safe_float(_get_val(r, ["attributes", "points"]), 0.0) for r in races)
        m[avg_points_key] = m[points_key] / len(races) if races else 0.0

        m[wins_key]    = sum(1 for r in races if effective_pos(r) == 1)
        m[podiums_key] = sum(1 for r in races if 1 <= effective_pos(r) <= 3)

        if top5_key is not None:
            m[top5_key] = sum(1 for r in races if 1 <= effective_pos(r) <= 5)

        m[top_finish_key] = sum(1 for r in races if 1 <= effective_pos(r) <= top_limit)

        m[fl_key] = sum(
            1 for r in races
            if _get_val(r, ["attributes", "fastestLap"]) is True
        )
        m[dnf_key] = sum(
            1 for r in races
            if _get_val(r, ["attributes", "dnf"]) is True
            or _get_val(r, ["attributes", "classification", "data", "attributes", "type"]) is not None
        )

        positions = [effective_pos(r) for r in races if effective_pos(r) > 0]
        m[best_finish_key] = min(positions) if positions else 0
        m[avg_finish_key]  = sum(positions) / len(races) if (races and positions) else -999

    # Race
    populate_race_data(
        MOTO_RACE_RACE,
        "racePoints", "avgPointsPerRace",
        "raceWins", "racePodiums",
        "top10FinishInRace", "fastestLapsInRace", "dnfInRace",
        "bestRaceFinish", "avgRaceFinishPosition",
        10, "top5FinishInRace"
    )

    # Sprint
    populate_race_data(
        MOTO_RACE_SPRINT,
        "sprintPoints", "avgPointsPerSprint",
        "sprintWins", "sprintPodiums",
        "top8FinishInSprint", "fastestLapsInSprint", "dnfInSprint",
        "bestSprintFinish", "avgSprintFinishPosition",
        8
    )

    m["points"] = m["racePoints"] + m["sprintPoints"]

    # ------------------------------------------------------------------ #
    #  populate_quali_data  –  QNR1 / QNR2 aggregation                    #
    #  Mirrors the Dart populateQualiData() logic exactly.                 #
    # ------------------------------------------------------------------ #
    def populate_quali_data(
            poles_key,
            first_row_key,
            q3_appearances_key,
            best_quali_key,
            avg_quali_key,
            avg_start_grid_key,
            avg_pos_gained_key,
            avg_finish_key,
            is_sprint: bool
    ):
        # QNR1 results where position > 2  → add +10 to position (they start from grid pos 13+)
        qnr1_raw = race_list_of_type(MOTO_RACE_QUALI1)
        qnr1_top2 = [r for r in qnr1_raw if _safe_int(_get_val(r, ["attributes", "position"])) <= 2]
        qnr1_rest = [r for r in qnr1_raw if _safe_int(_get_val(r, ["attributes", "position"])) > 2]

        # Rebuild qnr1_rest with position offset by +10
        qnr1_for_quali = []
        for r in qnr1_rest:
            import copy
            r_copy = copy.deepcopy(r)
            orig_pos = _safe_int(_get_val(r_copy, ["attributes", "position"]))
            r_copy["attributes"]["position"] = orig_pos + 10
            qnr1_for_quali.append(r_copy)

        qnr2 = race_list_of_type(MOTO_RACE_QUALI2)

        # Combined list used for qualifying position stats (official combined grid)
        qualis = qnr2 + qnr1_for_quali

        quali_positions = [
            _safe_int(_get_val(r, ["attributes", "position"]))
            for r in qualis
            if _get_val(r, ["attributes", "position"]) is not None
        ]
        m[best_quali_key] = min(quali_positions) if quali_positions else 0
        m[avg_quali_key]  = sum(quali_positions) / len(qualis) if quali_positions else -999

        # Grid for start position (qnr1 raw + qnr2, unmodified positions)
        qualis_for_grid = qnr1_raw + qnr2

        if is_sprint:
            # Sprint grid: sprintFinalPos ?? finalPos ?? position
            def sprint_grid_pos(r):
                sfp = _get_val(r, ["attributes", "sprintFinalPos"])
                if sfp is not None:
                    return _safe_int(sfp)
                fp = _get_val(r, ["attributes", "finalPos"])
                if fp is not None:
                    return _safe_int(fp)
                return _safe_int(_get_val(r, ["attributes", "position"]))

            m[poles_key]         = sum(1 for r in qualis_for_grid if sprint_grid_pos(r) == 1)
            m[first_row_key]     = sum(1 for r in qualis_for_grid if 1 <= sprint_grid_pos(r) <= 3)
            m[q3_appearances_key] = len(qnr2)

            grid_positions = [sprint_grid_pos(r) for r in qualis_for_grid]
            m[avg_start_grid_key] = sum(grid_positions) / len(qualis_for_grid) if qualis_for_grid else -999

        else:
            # Race grid: finalPos ?? position
            def race_grid_pos(r):
                fp = _get_val(r, ["attributes", "finalPos"])
                if fp is not None:
                    return _safe_int(fp)
                return _safe_int(_get_val(r, ["attributes", "position"]) or 0)

            m[poles_key]         = sum(1 for r in qualis_for_grid if race_grid_pos(r) == 1)
            m[first_row_key]     = sum(1 for r in qualis_for_grid if 1 <= race_grid_pos(r) <= 3)
            m[q3_appearances_key] = len(qnr2)

            grid_positions = [race_grid_pos(r) for r in qualis_for_grid]
            m[avg_start_grid_key] = sum(grid_positions) / len(qualis_for_grid) if qualis_for_grid else -999

        if m.get(avg_finish_key) == -999:
            m[avg_pos_gained_key] = -999
        else:
            m[avg_pos_gained_key] = m[avg_start_grid_key] - m[avg_finish_key]

    # Race quali
    populate_quali_data(
        "racePoles", "raceFirstRowStarts", "q3Appearances",
        "bestQualiPos", "avgRaceQualiPosition",
        "avgRaceStartGridPosition", "avgRacePositionGained",
        "avgRaceFinishPosition",
        is_sprint=False
    )

    # Sprint quali
    populate_quali_data(
        "sprintPoles", "sprintFirstRowStarts", "sprintQ3Appearances",
        "bestSprintQualiPos", "avgSprintQualiPosition",
        "avgSprintStartGridPosition", "avgSprintPositionGained",
        "avgSprintFinishPosition",
        is_sprint=True
    )

    # ------------------------------------------------------------------ #
    #  Unique GP count                                                     #
    # ------------------------------------------------------------------ #
    unique_gp_ids = {
        _get_val(r, ["attributes", "race", "data", "attributes", "grandPrix", "data", "id"])
        for r in race_results
        if _get_val(r, ["attributes", "race", "data", "attributes", "grandPrix", "data", "id"]) is not None
    }
    m["noOfGPs"] = len(unique_gp_ids)

    # ------------------------------------------------------------------ #
    #  Meta                                                                #
    # ------------------------------------------------------------------ #
    m["standings_id"]          = standing_id
    m["driver_season_grid_id"] = driver_season_grid_id
    m["is_primary_grid_id"]    = is_primary_grid_id
    m["position"]              = position

    return m
