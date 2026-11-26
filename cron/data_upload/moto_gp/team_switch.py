"""A rider who already has a season grid but rides for another team this weekend must not be written on
the grid of his old team: team points follow the grid's team link. Example: Iker Lecuona (#27), a Gresini
substitute earlier in 2026 (grid 92, linked to Gresini), rode for Ducati Lenovo in Portugal; his 7 points
(Sprint P9, Race P10) went to Gresini (368 instead of 361) and were missing at Ducati Lenovo (612 instead of 619).

The rule, for every session before its rows are written:
- Team of an API team name: over the weekend, each team standing takes the API team name most of its other
  riders ride under (the rider judged is left out; a tie gives no name); a name claimed by exactly one
  standing belongs to it. A team entered under two names (LCR) gets no name and never causes a move.
- A rider whose grid is linked to another standing than the one of his API team name (or to none) rode for
  that team. Over the finished sessions of the weekend: the seat is open (fewer than 2 other riders of that
  standing took part) in most sessions = substitute, counts for the team; otherwise a wild card, counts for
  no team (FIM Art. 1.28.4). Same vote as auto_grid.decide.
- The session is written on the rider's grid with that team link (an existing one, else a new one: same
  bike and colour as the team-mate, default photo, isOldGrid true as for the 2024 #87/#32 grids, linked to the team standing and added to the rider's
  driver standing so his own points stay complete). A "Test Team" entry on a team-linked grid is a wild
  card, and so is a third rider of a team under a name his two team-mates do not use. An unclear case
  keeps the current grid.
- A new grid and an unclear case are reported (the run ends red) so a person checks the decision and adds
  the photo. Reusing an existing grid is only logged.
"""
from collections import Counter

from loguru import logger

from cron.data_upload.moto_gp.auto_grid import DEFAULT_PHOTO, SESSION_ORDER, StrapiREST, team_name_of


def _is_test_team(name):
    return "test team" in (name or "").lower()


def names_to_standing(rows, grid_map, team_of, exclude=None):
    """rows: [(number, API team name)] (one session or a whole weekend) -> {API team name: team standing id}.
    Each team standing takes the name most of its riders ride under, one vote per rider and name, the rider
    being judged left out (his own entry must not name his old team: Lecuona alone on his Gresini grid in
    Portugal Q1 rode as Ducati Lenovo). A tie gives no name; a name claimed by two standings belongs to none."""
    by_standing = {}
    for n, t in set(rows):
        s = team_of.get(grid_map.get(n))
        if s is not None and t and n != exclude:
            by_standing.setdefault(s, []).append(t)
    claims = {}
    for s, names in by_standing.items():
        top = Counter(names).most_common(2)
        if len(top) > 1 and top[0][1] == top[1][1]:
            continue
        claims.setdefault(top[0][0], set()).add(s)
    return {t: next(iter(ss)) for t, ss in claims.items() if len(ss) == 1}


def suspects(rows, grid_map, team_of):
    """Numbers whose grid's team link differs from the standing of their API team name (others' votes), and
    test-team entries on a team-linked grid."""
    out = []
    for n, t in dict(rows).items():
        if n not in grid_map:
            continue
        cur = team_of.get(grid_map[n])
        if _is_test_team(t):
            if cur is not None:
                out.append(n)
            continue
        names = names_to_standing(rows, grid_map, team_of, exclude=n)
        if (t in names and cur != names[t]) or _extra_rider(n, t, rows, grid_map, team_of):
            out.append(n)
    return out


def _extra_rider(n, t, rows, grid_map, team_of):
    """A third rider counted for one team, under a name his two team-mates do not use: a wild card for
    another entry (Yamaha's test team enters as "Yamaha Factory Racing": Gardner Japan 2024, A. Fernandez
    Catalonia 2026, on grids linked to Yamaha and Pramac from their substitute rides)."""
    cur = team_of.get(grid_map.get(n))
    if cur is None:
        return False
    mates = {m: tt for m, tt in set(rows) if m != n and team_of.get(grid_map.get(m)) == cur}
    return len(mates) >= 2 and t not in set(mates.values())


def decide(num, sessions_rows, grid_map, team_of):
    """("substitute", standing id) | ("wildcard", standing id of the team he rode for, or None) | ("unclear", None).
    Open seat (fewer than 2 other riders of that standing took part) in most sessions = substitute."""
    mine = Counter(t for rows in sessions_rows for n, t in rows if n == num)
    if not mine:
        return "unclear", None
    tname = mine.most_common(1)[0][0]
    if _is_test_team(tname):
        return "wildcard", None
    flat = [x for rows in sessions_rows for x in rows]
    target = names_to_standing(flat, grid_map, team_of, exclude=num).get(tname)
    if target is None:
        return ("wildcard", None) if _extra_rider(num, tname, flat, grid_map, team_of) else ("unclear", None)
    votes = []
    for rows in sessions_rows:
        if num in {n for n, _ in rows}:
            votes.append(sum(1 for n, _ in rows if n != num and team_of.get(grid_map.get(n)) == target) < 2)
    return ("substitute", target) if sum(votes) * 2 > len(votes) else ("wildcard", target)


def choose(num, desired, grid_map, grids_of_num, team_of):
    """("keep", grid) | ("use", grid) | ("create", None). desired: team standing id, None = no team."""
    cur = grid_map[num]
    if team_of.get(cur) == desired:
        return "keep", cur
    cands = [g for g in grids_of_num if team_of.get(g) == desired]
    return ("use", max(cands)) if cands else ("create", None)


def plan_session(session_rows, weekend_rows, grid_map, team_of, grids_of):
    """{number: (decision, target standing, action, grid)} for the riders of one session the rule acts on.
    weekend_rows: per finished session [(number, API team name)], this session included."""
    flat = [x for rows in weekend_rows for x in rows]
    here = {n for n, _ in session_rows}
    found = [n for n in suspects(flat, grid_map, team_of) if n in here]  # weekend view: Q1 alone is not enough
    out = {}
    for num in found:
        decision, target = decide(num, weekend_rows, grid_map, team_of)
        if decision == "unclear":
            out[num] = (decision, None, "keep", grid_map[num])
            continue
        desired = target if decision == "substitute" else None
        action, gid = choose(num, desired, grid_map, grids_of.get(num, []), team_of)
        out[num] = (decision, target, action, gid)
    return out


class TeamCheck:
    """check(year, gp_short, classification, grid_map) -> (grid_map for this session, problems)."""

    def __init__(self, strapi, api, now_iso=None, bump=None):
        self.strapi, self.api, self.now_iso, self.bump = strapi, api, now_iso, bump

    def _season(self, year):
        season_id = self.strapi.get("seasons", {"filters[year][$eq]": str(year)})["data"][0]["id"]
        grids = self.strapi.get("season-grids", {
            "filters[season][id][$eq]": season_id, "pagination[pageSize]": 200,
            "populate[chassis][fields][0]": "id", "populate[driver][fields][0]": "lastName"})["data"]
        teams = self.strapi.get("team-standings", {"filters[season][id][$eq]": season_id, "pagination[pageSize]": 50,
                                                   "populate[seasonGrid][fields][0]": "id"})["data"]
        return season_id, grids, teams

    def _weekend_rows(self, year, gp_short, current):
        """[(number, API team name)] per finished session of the weekend; the current session at least."""
        out = []
        try:
            from cron.data_upload.moto_gp.corrections import final_api_session
            season_uuid = next(s for s in self.api("seasons") if str(s["year"]) == str(year))["id"]
            event = next(e for e in self.api(f"events?seasonUuid={season_uuid}")
                         if e.get("short_name") == gp_short and not e.get("test"))
            sessions = self.api(f"sessions?eventUuid={event['id']}&categoryUuid=e8c110ad-64aa-4e8e-8a86-f2f152f6a942")
            for st in SESSION_ORDER:
                s = final_api_session(sessions, st)
                if s and s.get("status") in ("FINISHED", "IN-PROGRESS", "INPROGRESS"):
                    cls = self.api(f"session/{s['id']}/classification?test=false").get("classification") or []
                    out.append([(c["rider"]["number"], team_name_of(c)) for c in cls])
        except Exception as e:
            logger.warning(f"team check: weekend sessions not read ({type(e).__name__}: {e}), using this session only")
        return [r for r in out if r] or [current]

    def check(self, year, gp_short, classification, grid_map):
        rows = [(c["rider"]["number"], team_name_of(c)) for c in classification]
        try:
            season_id, grids, teams = self._season(year)
        except Exception as e:
            return grid_map, [f"team check skipped, Strapi not read ({type(e).__name__}: {e}); "
                              f"check riders who changed team by hand"]
        team_of = {g["id"]: t["id"] for t in teams for g in t["attributes"]["seasonGrid"]["data"]}
        weekend = self._weekend_rows(year, gp_short, rows)
        if rows not in weekend:
            weekend = weekend + [rows]  # the session being written may not be listed as finished yet
        grids_of = {}
        for g in grids:
            grids_of.setdefault(g["attributes"].get("driverNumber"), []).append(g["id"])
        team_grids = {t["id"]: [g["id"] for g in t["attributes"]["seasonGrid"]["data"]] for t in teams}
        grid_by_id = {g["id"]: g for g in grids}
        out, problems = dict(grid_map), []
        for num, (decision, target, action, gid) in plan_session(rows, weekend, grid_map, team_of, grids_of).items():
            tname = dict(rows)[num]
            if decision == "unclear":
                problems.append(f"#{num} rides for {tname} but his grid {grid_map[num]} counts for team standing "
                                f"{team_of.get(grid_map[num])}; substitute or wild card is unclear, written on grid "
                                f"{grid_map[num]}: check the team link by hand")
                continue
            desired = target if decision == "substitute" else None
            if action == "keep":
                continue
            if action == "use":
                logger.info(f"#{num} rides for {tname} ({decision}): written on his grid {gid} (team standing {desired})")
                out[num] = gid
                continue
            try:
                gid = self._create(num, tname, decision, desired, target, season_id, grid_map, grid_by_id,
                                   team_of, team_grids, rows)
            except Exception as e:
                problems.append(f"#{num} rides for {tname} ({decision}) but no grid could be made "
                                f"({type(e).__name__}: {e}); written on grid {grid_map[num]}: fix the team points by hand")
                continue
            out[num] = gid
            problems.append(f"#{num} rides for {tname} ({decision}): new season grid {gid}"
                            f"{' linked to team standing ' + str(desired) if desired else ', no team link'}, "
                            f"added to his driver standing, default photo. Add the photo and check the decision.")
        return out, problems

    def _create(self, num, tname, decision, desired, target, season_id, grid_map, grid_by_id, team_of, team_grids, rows):
        cur = grid_by_id[grid_map[num]]["attributes"]
        mates = [n for n, t in rows if t == tname and n != num and team_of.get(grid_map.get(n)) == target]
        template = grid_by_id[grid_map[mates[0]]]["attributes"] if mates else cur
        chassis = ((template.get("chassis") or {}).get("data") or {}).get("id")
        driver = ((cur.get("driver") or {}).get("data") or {}).get("id")
        grid = self.strapi.post("season-grids", {"season": season_id, "driver": driver, "driverNumber": num,
                                                 "chassis": chassis, "teamColor": template.get("teamColor"),
                                                 "driverPhoto": DEFAULT_PHOTO, "isOldGrid": True,  # keeps his main grid
                                                 "publishedAt": self.now_iso})               # in the number map
        gid = grid["id"]
        if desired is not None:
            self.strapi.put(f"team-standings/{desired}", {"seasonGrid": team_grids[desired] + [gid]})
        standings = self.strapi.get("driver-standings", {"filters[season][id][$eq]": season_id, "pagination[pageSize]": 100,
                                                         "populate[seasonGrid][fields][0]": "id",
                                                         "populate[grids][fields][0]": "id"})["data"]
        old = grid_map[num]
        for s in standings:
            a = s["attributes"]
            primary = ((a.get("seasonGrid") or {}).get("data") or {}).get("id")
            extra = [g["id"] for g in ((a.get("grids") or {}).get("data") or [])]
            if old == primary or old in extra:
                keep = [primary] + [g for g in extra if g != primary]
                self.strapi.put(f"driver-standings/{s['id']}", {"grids": keep + [gid]})
                break
        if self.bump:
            self.bump()
        return gid


def make_handler():
    """Handler for the uploader: handler(year, gp_short, classification, grid_map) -> (grid_map, problems)."""
    from datetime import datetime, timezone
    from cron.data_upload.moto_gp.auto_grid import _bump_grid_cache
    from cron.data_upload.moto_gp.post_race import pulselive
    from cron.strapi_api.apis import get_headers
    from cron.utils import moto_graphql_end_point

    def handler(year, gp_short, classification, grid_map):
        strapi = StrapiREST(moto_graphql_end_point.rsplit("/graphql", 1)[0], get_headers(False))
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        return TeamCheck(strapi, pulselive, now_iso, _bump_grid_cache).check(year, gp_short, classification, grid_map)

    return handler
