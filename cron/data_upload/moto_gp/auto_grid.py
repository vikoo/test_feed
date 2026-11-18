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
                                        "populate[chassis][fields][0]": "id"})["data"]
    teams = strapi.get("team-standings", {"filters[season][id][$eq]": season_id, "pagination[pageSize]": 50,
                                          "populate[seasonGrid][fields][0]": "id"})["data"]
    team_of = {g["id"]: t["id"] for t in teams for g in t["attributes"]["seasonGrid"]["data"]}
    team_grids = {t["id"]: [g["id"] for g in t["attributes"]["seasonGrid"]["data"]] for t in teams}
    grid_by_id = {g["id"]: g for g in grids}
    grid_of = {}
    for g in sorted(grids, key=lambda g: g["attributes"].get("isOldGrid") is True, reverse=True):
        grid_of[g["attributes"]["driverNumber"]] = g["id"]  # non-old grids win (sorted last)

    for num in missing:
        c = riders.get(num)
        if not c:
            problems.append(f"#{num}: not in any classification of {gp_short}, grid not created")
            continue
        tname, full = team_name_of(c), c["rider"].get("full_name") or ""
        mates = [n for rows in sessions_rows for n, t in rows if t == tname and n != num and n in grid_of]
        if not mates:
            problems.append(f"#{num} {full} ({tname}): no team-mate grid to copy the bike from, create the grid by hand")
            continue
        template = grid_by_id[grid_of[mates[0]]]["attributes"]
        chassis = ((template.get("chassis") or {}).get("data") or {}).get("id")
        decision, team_id = decide(num, tname, sessions_rows, grid_of, team_of)

        last = strapi_last_name(full)
        drivers = strapi.get("drivers", {"filters[lastName][$containsi]": full.split()[-1] if full else "", "pagination[pageSize]": 50})["data"]
        match = [d for d in drivers if _norm(d["attributes"].get("lastName")) == _norm(last)]
        plan = {"number": num, "name": full, "team": tname, "decision": decision, "team_standing": team_id,
                "chassis": chassis, "teamColor": template.get("teamColor"), "driver": match[0]["id"] if match else None}
        if apply:
            driver_id = plan["driver"]
            if driver_id is None:
                country = ((c["rider"].get("country") or {}).get("name")) or None
                surname = full.split()[-1] if full else ""
                driver_id = strapi.post("drivers", {"lastName": last, "initials": f"{full[:1]}. {surname[:3]}",
                                                    "number": num, "country": country, "nationality": country,
                                                    "publishedAt": now_iso})["id"]
            grid = strapi.post("season-grids", {"season": season_id, "driver": driver_id, "driverNumber": num,
                                                "chassis": chassis, "teamColor": template.get("teamColor"),
                                                "driverPhoto": DEFAULT_PHOTO, "publishedAt": now_iso})
            plan["grid"] = grid["id"]
            if decision == "substitute":
                strapi.put(f"team-standings/{team_id}", {"seasonGrid": team_grids[team_id] + [grid["id"]]})
        created.append(plan)
        extra = " Bike copied from the team-mate (chassis %s); a wild card may need its own chassis." % chassis \
            if decision != "substitute" else ""
        problems.append(f"new season grid for #{num} {full} ({tname}): {decision}"
                        f"{' for team standing ' + str(team_id) if team_id else ''}, default photo. "
                        f"Add the photo and check the team link.{extra}")
    return created, problems


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
            _bump_grid_cache()
        return len(created) == len(missing), problems

    return handler


def _bump_grid_cache():
    """driverTeamTrackSeasonTyre: the app refetches season grids."""
    from cron.strapi_api.apis import get_graphql_endpoint, get_headers
    from cron.strapi_api.api_queries import mutation_update_config_for_gp
    from cron.utils import get_current_epoch
    q = mutation_update_config_for_gp.replace("grandPrixRace", "driverTeamTrackSeasonTyre")
    requests.post(get_graphql_endpoint(False), json={"query": q, "variables": {"input": {"driverTeamTrackSeasonTyre": get_current_epoch()}}},
                  headers=get_headers(False), timeout=30)
