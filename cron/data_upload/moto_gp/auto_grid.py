"""Create the season grid of a new rider (substitute or wild card) when a session lists a rider number that
has no grid in Strapi, so the session can be ingested instead of skipped.

- Rider record: found by "F. Surname" (the Strapi lastName convention, e.g. "J. Dixon"); created when missing.
- Grid: same bike (chassis) and team colour as a team-mate's grid in the same weekend, the default rider
  photo (the real photo stays a manual step), not marked old.
- Team link (team points): session by session, among the sessions the new rider took part in, his team is
  given by team-mates with the same API team name; the seat is open when fewer than 2 riders linked to that
  team took part. Majority of those sessions: open seat = substitute, linked to the team; otherwise a wild
  card, not linked. "Test Team" entries are wild cards. Anything else is "unclear": the grid is created
  without a team link. Checked against every substitute and wild card decided by hand in 2024 to 2026:
  25 equal, 3 unclear, 0 different.
- Every creation is reported (the run ends red), so a person adds the photo and checks the decision.
"""
import re
import time
import unicodedata

import requests
from loguru import logger

DEFAULT_PHOTO = "https://purple-sector-bucket.s3.ap-south-1.amazonaws.com/wheelie/Season2025/riders/default_rider.png"
SESSION_ORDER = ("FP1", "PRACTICE", "FP2", "QNR1", "QNR2", "Sprint", "Race")
# Strapi stores short country names ("UK", not the API's "United Kingdom of Great Britain and Northern Ireland").
COUNTRY_BY_ISO = {"GB": "UK", "TR": "Türkiye", "US": "USA", "CZ": "Czechia", "NL": "Netherlands", "KR": "South Korea"}


def country_name(rider: dict):
    c = rider.get("country") or {}
    return COUNTRY_BY_ISO.get((c.get("iso") or "").upper()) or c.get("name") or None


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]", "", s)


def strapi_last_name(full_name: str) -> str:
    """'Jake Dixon' -> 'J. Dixon', 'Fabio Di Giannantonio' -> 'F. Di Giannantonio'."""
    parts = (full_name or "").split()
    return f"{parts[0][0]}. {' '.join(parts[1:])}" if len(parts) > 1 else (full_name or "")


def team_name_of(c: dict) -> str:
    return (c.get("team") or {}).get("name") or c.get("team_name") or ""


def decide(num: int, team_name: str, sessions_rows: list, grid_of: dict, team_of: dict):
    """("substitute", team standing id) | ("wildcard", None) | ("unclear", None).
    sessions_rows: per session [(number, team name)]; grid_of: number -> grid id of riders with a grid;
    team_of: grid id -> team standing id."""
    if team_name and "test team" in team_name.lower():
        return "wildcard", None
    votes, teams_seen = [], set()
    for rows in sessions_rows:
        if num not in {n for n, _ in rows}:
            continue
        mates = [n for n, t in rows if t == team_name and n != num and n in grid_of]
        if not mates:
            continue
        teams = {team_of.get(grid_of[n]) for n in mates}
        if len(teams) != 1 or None in teams:
            return "unclear", None
        team = teams.pop()
        teams_seen.add(team)
        linked_present = sum(1 for n, _ in rows if n != num and n in grid_of and team_of.get(grid_of[n]) == team)
        votes.append(linked_present < 2)
    if not votes or len(teams_seen) != 1:
        return "unclear", None
    return ("substitute", teams_seen.pop()) if sum(votes) * 2 > len(votes) else ("wildcard", None)


class StrapiREST:
    def __init__(self, base: str, headers: dict):
        self.base, self.h = base.rstrip("/"), headers

    def get(self, path, params=None):
        p = dict(params or {})
        p["_t"] = int(time.time() * 1000)
        r = requests.get(f"{self.base}/api/{path}", params=p, headers=self.h, timeout=30)
        r.raise_for_status()
        return r.json()

    def post(self, path, data):
        r = requests.post(f"{self.base}/api/{path}", json={"data": data}, headers=self.h, timeout=30)
        r.raise_for_status()
        return r.json()["data"]

    def put(self, path, data):
        r = requests.put(f"{self.base}/api/{path}", json={"data": data}, headers=self.h, timeout=30)
        r.raise_for_status()
        return r.json()["data"]


def plan_and_create(year: str, gp_short: str, missing: list, api, strapi, apply: bool = True, now_iso=None):
    """Create grids for the missing rider numbers of one Grand Prix. Returns (created [dict], problems [str])."""
    created, problems = [], []
    season_uuid = next(s for s in api("seasons") if str(s["year"]) == str(year))["id"]
    event = next((e for e in api(f"events?seasonUuid={season_uuid}") if e.get("short_name") == gp_short and not e.get("test")), None)
    if not event:
        return [], [f"{gp_short}: event not found, grids for {missing} not created"]
    from cron.data_upload.moto_gp.corrections import SESSION_MAP, final_api_session
    sessions = api(f"sessions?eventUuid={event['id']}&categoryUuid=e8c110ad-64aa-4e8e-8a86-f2f152f6a942")
    sessions_rows, riders = [], {}
    for st in SESSION_ORDER:
        s = final_api_session(sessions, st)
        if not s or s.get("status") not in ("FINISHED", "IN-PROGRESS", "INPROGRESS"):
            continue
        cls = api(f"session/{s['id']}/classification?test=false").get("classification") or []
        sessions_rows.append([(c["rider"]["number"], team_name_of(c)) for c in cls])
        for c in cls:
            riders.setdefault(c["rider"]["number"], c)

    season = strapi.get("seasons", {"filters[year][$eq]": str(year)})["data"]
    if not season:
        return [], [f"season {year} not in Strapi, grids for {missing} not created"]
    season_id = season[0]["id"]
    grids = strapi.get("season-grids", {"filters[season][id][$eq]": season_id, "pagination[pageSize]": 100,
                                        "populate[chassis][fields][0]": "name", "populate[chassis][fields][1]": "powerUnit"})["data"]
    teams = strapi.get("team-standings", {"filters[season][id][$eq]": season_id, "pagination[pageSize]": 50,
                                          "populate[seasonGrid][fields][0]": "id"})["data"]
    team_of = {g["id"]: t["id"] for t in teams for g in t["attributes"]["seasonGrid"]["data"]}
    team_grids = {t["id"]: [g["id"] for g in t["attributes"]["seasonGrid"]["data"]] for t in teams}
    grid_by_id = {g["id"]: g for g in grids}
    grid_of = {}
    for g in sorted(grids, key=lambda g: g["attributes"].get("isOldGrid") is True, reverse=True):
        grid_of[g["attributes"]["driverNumber"]] = g["id"]  # non-old grids win (sorted last)
    current = {g["attributes"]["driverNumber"] for g in grids if g["attributes"].get("isOldGrid") is not True}

    for num in missing:
        if num in current:
            # The number has a current grid already (a lookup that missed it, e.g. a page limit): never a duplicate.
            problems.append(f"#{num}: a current season grid exists in Strapi but the uploader did not see it; "
                            f"no grid created, check the grid lookup")
            continue
        c = riders.get(num)
        if not c:
            problems.append(f"#{num}: not in any classification of {gp_short}, grid not created")
            continue
        tname, full = team_name_of(c), c["rider"].get("full_name") or ""
        mates = [n for rows in sessions_rows for n, t in rows if t == tname and n != num and n in grid_of]
        new_team = not mates
        if new_team:
            # A team with no rider in Strapi (new team): the bike of the same make (factory entry first), no
            # team link. The whole session is ingested instead of being blocked by one rider.
            template = factory_template(grids, (c.get("constructor") or {}).get("name"))
            if template is None:
                problems.append(f"#{num} {full} ({tname}, {(c.get('constructor') or {}).get('name')}): no team-mate and "
                                f"no bike of this make in Strapi; create the chassis and grid by hand")
                continue
            decision, team_id = "unclear", None
        else:
            template = grid_by_id[grid_of[mates[0]]]["attributes"]
            decision, team_id = decide(num, tname, sessions_rows, grid_of, team_of)
        chassis = ((template.get("chassis") or {}).get("data") or {}).get("id")

        last = strapi_last_name(full)
        drivers = strapi.get("drivers", {"filters[lastName][$containsi]": full.split()[-1] if full else "", "pagination[pageSize]": 50})["data"]
        match = [d for d in drivers if _norm(d["attributes"].get("lastName")) == _norm(last)]
        if len(match) > 1:
            same_number = [d for d in match if d["attributes"].get("number") == num]
            if len(same_number) != 1:
                problems.append(f"#{num} {full}: {len(match)} rider records named {last!r} in Strapi "
                                f"({[d['id'] for d in match]}); no grid created, create it by hand")
                continue
            match = same_number
        plan = {"number": num, "name": full, "team": tname, "decision": decision, "team_standing": team_id,
                "chassis": chassis, "teamColor": template.get("teamColor"), "driver": match[0]["id"] if match else None}
        if apply:
            step = "driver"
            try:
                driver_id = plan["driver"]
                if driver_id is None:
                    country = country_name(c["rider"])
                    surname = full.split()[-1] if full else ""
                    driver_id = strapi.post("drivers", {"lastName": last, "initials": f"{full[:1]}. {surname[:3]}",
                                                        "number": num, "country": country, "nationality": country,
                                                        "publishedAt": now_iso})["id"]
                    plan["driver"] = driver_id
                step = "season grid"
                grid = strapi.post("season-grids", {"season": season_id, "driver": driver_id, "driverNumber": num,
                                                    "chassis": chassis, "teamColor": template.get("teamColor"),
                                                    "driverPhoto": DEFAULT_PHOTO, "publishedAt": now_iso})
                plan["grid"] = grid["id"]
                if decision == "substitute":
                    step = "team link"
                    for attempt in range(3):
                        try:
                            strapi.put(f"team-standings/{team_id}", {"seasonGrid": team_grids[team_id] + [grid["id"]]})
                            break
                        except Exception:
                            if attempt == 2:
                                raise
                            time.sleep(5)
            except Exception as e:
                if "grid" in plan:
                    created.append(plan)  # the grid exists: the session can be ingested, the cache must be bumped
                problems.append(f"#{num} {full}: {step} creation failed ({type(e).__name__}: {e}). "
                                + (f"Grid {plan['grid']} exists: link it to team standing {team_id} by hand."
                                   if step == "team link" else "Nothing more was created; check Strapi."))
                continue
        created.append(plan)
        extra = (f" New team: bike and colour copied from the {(c.get('constructor') or {}).get('name')} factory entry "
                 f"(chassis {chassis}); create the team, its chassis and team standing, then fix this grid."
                 if new_team else
                 " Bike copied from the team-mate (chassis %s); a wild card may need its own chassis." % chassis
                 if decision != "substitute" else "")
        problems.append(f"new season grid for #{num} {full} ({tname}): {decision}"
                        f"{' for team standing ' + str(team_id) if team_id else ''}, default photo. "
                        f"Add the photo and check the team link.{extra}")
    return created, problems


def factory_template(grids: list, make: str):
    """Grid attributes to copy for a rider of a new team: a current grid on a chassis of the same make,
    the factory entry first, never a test bike. None when Strapi has no bike of that make."""
    if not make:
        return None
    cands = []
    for g in grids:
        a = g["attributes"]
        ch = ((a.get("chassis") or {}).get("data") or {})
        ca = ch.get("attributes") or {}
        if a.get("isOldGrid") is True or (ca.get("powerUnit") or "").lower() != make.lower():
            continue
        name = ca.get("name") or ""
        if "test" in name.lower():
            continue
        cands.append((0 if name.lower().startswith("factory") else 1, g["id"], a))
    return min(cands, key=lambda x: (x[0], x[1]))[2] if cands else None


def make_handler():
    """Handler for the uploader: handler(year, gp_short, missing numbers) -> (all created, problems)."""
    from datetime import datetime, timezone
    from cron.data_upload.moto_gp.post_race import pulselive
    from cron.strapi_api.apis import get_headers, update_config_for_season
    from cron.utils import moto_graphql_end_point

    def handler(year, gp_short, missing):
        strapi = StrapiREST(moto_graphql_end_point.rsplit("/graphql", 1)[0], get_headers(False))
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        created, problems = plan_and_create(str(year), gp_short, list(missing), pulselive, strapi, True, now_iso)
        if created:
            try:
                _bump_grid_cache()
            except Exception as e:
                problems.append(f"grid cache bump failed, bump driverTeamTrackSeasonTyre and chassisSeasonGrid by hand: {e}")
        return len(created) == len(missing), problems

    return handler


def _bump_grid_cache():
    """driverTeamTrackSeasonTyre and chassisSeasonGrid (mz-ops strapi-knowledge-base: season grid changes):
    the app refetches riders and season grids. Raises if Strapi refuses."""
    from cron.strapi_api.apis import get_graphql_endpoint, get_headers
    from cron.strapi_api.api_queries import mutation_update_config_for_gp
    from cron.utils import get_current_epoch
    for key in ("driverTeamTrackSeasonTyre", "chassisSeasonGrid"):
        q = mutation_update_config_for_gp.replace("grandPrixRace", key)
        r = requests.post(get_graphql_endpoint(False), json={"query": q, "variables": {"input": {key: get_current_epoch()}}},
                          headers=get_headers(False), timeout=30)
        r.raise_for_status()
        if (r.json() or {}).get("errors"):
            raise RuntimeError(f"{key}: {r.json()['errors']}")
