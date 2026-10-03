"""Make sure every rider in the official MotoGP rider standings has a driver standing row in Strapi.

The stats job only updates existing driver standing rows. A substitute rider who starts a Sprint or
Race (so appears in the official standings) but has no row would never be ranked, which shifts every
rider below them. Riders are matched by the driver number of ALL their season grids, so a rider whose
results are split over two grids is never treated as missing.

Creating season grids and linking riders to team standings stays a manual step: whether a rider is a
substitute (counts for the team) or a wild card (does not, FIM Art. 1.28.4) is not in the data.
"""
from loguru import logger

MAX_CREATIONS_PER_RUN = 3
SCORING_SESSION_TYPES = ("Race", "Sprint")


def _data(obj):
    return (obj or {}).get("data")


def _season_id(driver_standings):
    for standing in driver_standings:
        season = _data((standing.get("attributes") or {}).get("season"))
        if season and season.get("id") is not None:
            return season["id"]
    return None


def standing_driver_numbers(driver_standings):
    """Driver numbers covered by existing standing rows (primary grid and every extra grid)."""
    numbers = set()
    for standing in driver_standings:
        attrs = standing.get("attributes") or {}
        grids = [_data(attrs.get("seasonGrid"))] + list(_data(attrs.get("grids")) or [])
        for grid in grids:
            number = ((grid or {}).get("attributes") or {}).get("driverNumber")
            if number is not None:
                numbers.add(int(number))
    return numbers


def official_rider_numbers(rider_standings):
    riders = ((rider_standings or {}).get("classification") or {}).get("rider") or []
    numbers = []
    for entry in riders:
        number = (entry.get("rider") or {}).get("number")
        if number is not None:
            numbers.append(int(number))
    return numbers


def plan_missing_driver_standings(official_numbers, driver_standings, grids_by_number):
    """Return ([(number, grid_id)] to create, [(number, reason)] skipped)."""
    present = standing_driver_numbers(driver_standings)
    to_create, skipped = [], []
    for number in official_numbers:
        if number in present:
            continue
        grid_ids = grids_by_number.get(number, [])
        if len(grid_ids) == 1:
            to_create.append((number, grid_ids[0]))
        elif not grid_ids:
            skipped.append((number, "no active season grid"))
        else:
            skipped.append((number, f"more than one active season grid {grid_ids}"))
    if len(to_create) > MAX_CREATIONS_PER_RUN:
        skipped.extend((number, "too many missing riders in one run") for number, _ in to_create)
        to_create = []
    return to_create, skipped


def ensure_driver_standings(driver_standings, team_standings, fetch_official, fetch_grids, exists, create):
    """Return driver_standings plus an in-memory entry for every row created. Never raises."""
    result = list(driver_standings)
    try:
        official = official_rider_numbers(fetch_official())
        if not official:
            logger.warning("official rider standings empty, not checking for missing driver standings")
            return result
        to_create, skipped = plan_missing_driver_standings(official, result, fetch_grids())
        for number, reason in skipped:
            logger.error(f"rider #{number} is in the official standings but has no driver standing: {reason}. Fix manually.")
        season_id = _season_id(result)
        if to_create and season_id is None:
            logger.error("cannot create driver standings: season id unknown")
            return result
        team_grid_ids = {
            g.get("id")
            for t in team_standings
            for g in (_data((t.get("attributes") or {}).get("seasonGrid")) or [])
        }
        for number, grid_id in to_create:
            try:
                if exists(grid_id):
                    logger.warning(f"driver standing for grid {grid_id} (#{number}) already exists, skipping create")
                    continue
                position = len(result) + 1
                new_id = create(season_id, grid_id, position)
            except Exception:
                logger.exception(f"failed to create driver standing for rider #{number} (grid {grid_id})")
                continue
            logger.warning(f"created driver standing {new_id} for rider #{number} (grid {grid_id})")
            if grid_id not in team_grid_ids:
                logger.warning(
                    f"grid {grid_id} (#{number}) is not linked to any team standing: link it if the rider is a "
                    "substitute (counts for the team), leave it if a wild card (does not count, Art. 1.28.4)"
                )
            result.append({
                "id": new_id,
                "attributes": {
                    "position": position,
                    "season": {"data": {"id": season_id}},
                    "seasonGrid": {"data": {"id": grid_id, "attributes": {"driverNumber": number}}},
                },
            })
    except Exception:
        logger.exception("could not check for missing driver standings, continuing with the existing rows")
    return result


def uncounted_result_grids(all_race_results, driver_standings):
    """{grid_id: count} of Race/Sprint results on grids that no driver standing counts."""
    counted = set()
    for standing in driver_standings:
        attrs = standing.get("attributes") or {}
        for grid in [_data(attrs.get("seasonGrid"))] + list(_data(attrs.get("grids")) or []):
            if grid and grid.get("id") is not None:
                counted.add(grid["id"])
    uncounted = {}
    for result in all_race_results:
        attrs = result.get("attributes") or {}
        race_type = (((_data(attrs.get("race")) or {}).get("attributes")) or {}).get("type")
        grid_id = (_data(attrs.get("seasonGrid")) or {}).get("id")
        if race_type in SCORING_SESSION_TYPES and grid_id is not None and grid_id not in counted:
            uncounted[grid_id] = uncounted.get(grid_id, 0) + 1
    return uncounted


def warn_uncounted_result_grids(all_race_results, driver_standings):
    for grid_id, count in uncounted_result_grids(all_race_results, driver_standings).items():
        logger.warning(
            f"{count} Race/Sprint results are on season grid {grid_id}, which no driver standing counts. "
            "Link the grid to its rider's standing (grids relation)."
        )
