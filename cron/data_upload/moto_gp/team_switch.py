"""A rider who already has a season grid but rides for another team this weekend must not be written on
the grid of his old team: team points follow the grid's team link. Example: Iker Lecuona (#27), a Gresini
substitute earlier in 2026 (grid 92, linked to Gresini), rode for Ducati Lenovo in Portugal; his 7 points
(Sprint P9, Race P10) went to Gresini (368 instead of 361) and were missing at Ducati Lenovo (612 instead of 619).

The rule, for every session before its rows are written:
- Team of an API team name: over the weekend, each team standing takes the API team name most of its other
  riders ride under (the rider judged is left out; a tie gives no name); a name claimed by exactly one
  standing belongs to it. A team entered under two names (LCR) gets no name and never causes a move.
- A rider whose grid is linked to another standing than the one of his API team name rode for that team.
  Over the finished sessions of the weekend: the seat is open (fewer than 2 other riders of that standing
  took part) in most sessions = substitute, counts for the team; otherwise a wild card, counts for no team
  (FIM Art. 1.28.4). Same vote as auto_grid.decide.
- Wild card without a team name: a "Test Team" entry on a team-linked grid, or a third rider of his grid's
  team, on the same make of bike, under a name his two team-mates do not use (Yamaha's test team enters as
  "Yamaha Factory Racing"). On another make (a substitute at a team listed under two names) it is unclear.
- The session is written on the rider's grid with that team link. If none exists, a new one is made: same
  bike and colour as the team-mate, default photo, isOldGrid true (keeps his main grid in the number map,
  as the 2024 #87/#32 grids), linked to the team standing and added to his driver standing. A grid left
  half made by a failed write (no team link, not in his driver standing) is reused and completed.
- Nothing is changed when the weekend's sessions cannot be read (one session alone can mislead: Lecuona
  and Marquez alone in a Q1 would name Gresini "Ducati Lenovo").
- New grids, repairs and unclear cases are reported once per run (the run ends red) so a person checks the
  decision and adds the photo. Reusing a complete grid is only logged.
"""
import time
from collections import Counter

from loguru import logger

from cron.data_upload.moto_gp.auto_grid import DEFAULT_PHOTO, SESSION_ORDER, StrapiREST, team_name_of


def _is_test_team(name):
    return "test team" in (name or "").lower()


def _int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return x


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


def _third_rider(n, t, rows, grid_map, team_of):
    """A third rider counted for his grid's team, under a name his two team-mates do not use."""
    cur = team_of.get(grid_map.get(n))
    if cur is None:
        return False
    mates = {m: tt for m, tt in set(rows) if m != n and team_of.get(grid_map.get(m)) == cur}
    return len(mates) >= 2 and t not in set(mates.values())


def _extra_rider(n, t, rows, grid_map, team_of, cons):
    """A third rider counted for his grid's team, on that team's make of bike, under a name his two team-mates
    do not use: a wild card for another entry (Gardner Japan 2024, A. Fernandez Catalonia 2026, Yamaha test
    team as "Yamaha Factory Racing"). cons: number -> make; another make than his team-mates' is never a wild
    card of this kind (Lecuona as an LCR substitute while both Gresini riders race)."""
    cur = team_of.get(grid_map.get(n))
    if cur is None:
        return False
    mates = {m: tt for m, tt in set(rows) if m != n and team_of.get(grid_map.get(m)) == cur}
    if len(mates) < 2 or t in set(mates.values()):
        return False
    makes = {cons.get(m) for m in mates}
    return cons.get(n) is not None and makes == {cons.get(n)}


def _open_seat_same_make(n, rows, grid_map, team_of, cons):
    """Another team on his make of bike with fewer than 2 riders this weekend: he may be its substitute
    under a second team name (an HRC test rider as "Castrol Honda LCR" while LCR's other rider is
    "Pro Honda LCR"), so a wild card cannot be told apart: unclear."""
    cur, make = team_of.get(grid_map.get(n)), cons.get(n)
    riders = {}
    for m, _ in set(rows):
        s = team_of.get(grid_map.get(m))
        if m != n and s is not None and s != cur:
            riders.setdefault(s, set()).add(m)
    return any(len(ms) < 2 and {cons.get(m) for m in ms} == {make} for ms in riders.values())


def suspects(rows, grid_map, team_of, cons=None):
    """Numbers whose grid's team link differs from the standing of their API team name (others' votes),
    test-team entries on a team-linked grid, and extra riders (see _extra_rider)."""
    cons = cons or {}
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
        if (t in names and cur != names[t]) or _third_rider(n, t, rows, grid_map, team_of):  # decide() sorts it out
            out.append(n)
    return out


def decide(num, sessions_rows, grid_map, team_of, cons=None):
    """("substitute", standing id) | ("wildcard", standing id of the team he rode for, or None) | ("unclear", None).
    Open seat (fewer than 2 other riders of that standing took part) in most sessions = substitute."""
    cons = cons or {}
    mine = Counter(t for rows in sessions_rows for n, t in rows if n == num)
    if not mine:
        return "unclear", None
    tname = mine.most_common(1)[0][0]
    if _is_test_team(tname):
        return "wildcard", None
    flat = [x for rows in sessions_rows for x in rows]
    target = names_to_standing(flat, grid_map, team_of, exclude=num).get(tname)
    if target is None:
        if _extra_rider(num, tname, flat, grid_map, team_of, cons) and not _open_seat_same_make(num, flat, grid_map, team_of, cons):
            return "wildcard", None
        return "unclear", None
    votes = []
    for rows in sessions_rows:
        if num in {n for n, _ in rows}:
            votes.append(sum(1 for n, _ in rows if n != num and team_of.get(grid_map.get(n)) == target) < 2)
    return ("substitute", target) if sum(votes) * 2 > len(votes) else ("wildcard", target)


def choose(num, desired, grid_map, grids_of_num, team_of, counted=frozenset()):
    """("keep", grid) | ("use", grid) | ("create", None). desired: team standing id, None = no team.
    counted: grids some driver standing lists. A grid of this rider with no team link that no driver
    standing lists was left half made by a failed write (it may be the map's grid: a new grid is marked old
    and becomes the newest old grid): reused and completed before creating another.
    grids_of_num: this rider's grids only (same rider record), made by this rule (old grids)."""
    cur = grid_map[num]
    if team_of.get(cur) == desired and (desired is not None or cur in counted):
        return "keep", cur
    cands = [g for g in grids_of_num if team_of.get(g) == desired and (desired is not None or g in counted)]
    if cands:
        return "use", max(cands)
    orphans = [g for g in grids_of_num if team_of.get(g) is None and g not in counted]
    return ("use", max(orphans)) if orphans else ("create", None)


def plan_session(session_rows, weekend_rows, grid_map, team_of, grids_of, cons=None, counted=frozenset()):
    """{number: (decision, target standing, action, grid)} for the riders of one session the rule acts on.
    weekend_rows: per finished session [(number, API team name)], this session included."""
    flat = [x for rows in weekend_rows for x in rows]
    here = {n for n, _ in session_rows}
    found = [n for n in suspects(flat, grid_map, team_of, cons) if n in here]  # weekend view: Q1 alone is not enough
    out = {}
    for num in found:
        decision, target = decide(num, weekend_rows, grid_map, team_of, cons)
        if decision == "unclear":
            out[num] = (decision, None, "keep", grid_map[num])
            continue
        desired = target if decision == "substitute" else None
        action, gid = choose(num, desired, grid_map, grids_of.get(num, []), team_of, counted)
        out[num] = (decision, target, action, gid)
    return out


class TeamCheck:
    """check(year, gp_short, classification, grid_map) -> (grid_map for this session, problems).
    One instance per run: each problem is reported once."""

    def __init__(self, strapi, api, now_iso=None, bump=None):
        self.strapi, self.api, self.now_iso, self.bump = strapi, api, now_iso, bump
        self.reported = set()

    def _all(self, path, params):
        out, page = [], 1
        while True:  # Strapi caps a page at 100
            j = self.strapi.get(path, {**params, "pagination[pageSize]": 100, "pagination[page]": page})
            out += j["data"]
            if page >= ((j.get("meta") or {}).get("pagination") or {}).get("pageCount", 1):
                return out
            page += 1

    def _season(self, year):
        season_id = self.strapi.get("seasons", {"filters[year][$eq]": str(year)})["data"][0]["id"]
        grids = self._all("season-grids", {"filters[season][id][$eq]": season_id,
                                           "populate[chassis][fields][0]": "id", "populate[driver][fields][0]": "lastName"})
        teams = self._all("team-standings", {"filters[season][id][$eq]": season_id, "populate[seasonGrid][fields][0]": "id"})
        drivers = self._all("driver-standings", {"filters[season][id][$eq]": season_id,
                                                 "populate[seasonGrid][fields][0]": "id", "populate[grids][fields][0]": "id"})
        return season_id, grids, teams, drivers

    def _weekend(self, year, gp_short):
        """([(number, API team name)] per finished session, {number: make}); None when not readable."""
        try:
            from cron.data_upload.moto_gp.corrections import final_api_session
            season_uuid = next(s for s in self.api("seasons") if str(s["year"]) == str(year))["id"]
            event = next(e for e in self.api(f"events?seasonUuid={season_uuid}")
                         if e.get("short_name") == gp_short and not e.get("test"))
            sessions = self.api(f"sessions?eventUuid={event['id']}&categoryUuid=e8c110ad-64aa-4e8e-8a86-f2f152f6a942")
            out, cons = [], {}
            for st in SESSION_ORDER:
                s = final_api_session(sessions, st)
                if s and s.get("status") in ("FINISHED", "IN-PROGRESS", "INPROGRESS"):
                    cls = self.api(f"session/{s['id']}/classification?test=false").get("classification") or []
                    out.append([(c["rider"]["number"], team_name_of(c)) for c in cls])
                    cons.update({c["rider"]["number"]: (c.get("constructor") or {}).get("name") for c in cls})
            out = [r for r in out if r]
            return (out, cons) if out else None  # nothing finished yet: one session alone can mislead
        except Exception as e:
            logger.warning(f"team check: weekend sessions not read ({type(e).__name__}: {e})")
            return None

    def _report(self, problems, msg):
        if msg not in self.reported:
            self.reported.add(msg)
            problems.append(msg)

    def check(self, year, gp_short, classification, grid_map):
        rows = [(c["rider"]["number"], team_name_of(c)) for c in classification]
        here_cons = {c["rider"]["number"]: (c.get("constructor") or {}).get("name") for c in classification}
        problems = []
        try:
            season_id, grids, teams, drivers = self._season(year)
        except Exception as e:
            self._report(problems, f"team check skipped, Strapi not read ({type(e).__name__}: {e}); "
                                   f"check riders who changed team by hand")
            return grid_map, problems
        gm = {n: _int(g) for n, g in grid_map.items()}  # the uploader's map comes from GraphQL: ids are strings
        team_of = {g["id"]: t["id"] for t in teams for g in t["attributes"]["seasonGrid"]["data"]}
        weekend = self._weekend(year, gp_short)
        if weekend is None:
            if suspects(rows, gm, team_of, here_cons):
                self._report(problems, f"{gp_short}: team check not applied, the weekend's sessions could not be read; "
                                       f"riders {suspects(rows, gm, team_of, here_cons)} may ride for another team: check by hand")
            return grid_map, problems
        sessions, cons = weekend
        cons = {**cons, **here_cons}
        if not any({n for n, _ in s} == {n for n, _ in rows} for s in sessions):
            sessions = sessions + [rows]  # the session being written may not be listed as finished yet
        driver_of = {g["id"]: ((g["attributes"].get("driver") or {}).get("data") or {}).get("id") for g in grids}
        old = {g["id"] for g in grids if g["attributes"].get("isOldGrid") is True}
        grids_of = {}
        for g in grids:
            n = g["attributes"].get("driverNumber")
            if n in gm and driver_of[g["id"]] == driver_of.get(gm[n]) and (g["id"] in old or g["id"] == gm[n] or team_of.get(g["id"]) is not None or g["id"] in {x for d in drivers for x in self._ds_grids(d)}):
                grids_of.setdefault(n, []).append(g["id"])
        counted = {x for d in drivers for x in self._ds_grids(d)}
        out = dict(grid_map)
        for num, (decision, target, action, gid) in plan_session(rows, sessions, gm, team_of, grids_of, cons, counted).items():
            tname = dict(rows)[num]
            if decision == "unclear":
                self._report(problems, f"#{num} rides for {tname} but his grid {gm[num]} counts for team standing "
                                       f"{team_of.get(gm[num])}; substitute or wild card is unclear, written on grid "
                                       f"{gm[num]}: check the team link by hand")
                continue
            desired = target if decision == "substitute" else None
            if action == "keep" and gm[num] in counted:
                continue  # his grid already counts for the right team and for him
            made, step = action == "create", "season grid"
            try:
                if made:
                    gid = self._create_grid(num, tname, target, season_id, gm, grids, team_of, rows)
                step = "team link"
                fixed = self._ensure_team(gid, desired, teams)
                step = "driver standing"
                fixed += self._ensure_driver(gid, set(grids_of.get(num, [])) | {gm[num]}, drivers)
                if (made or fixed) and self.bump:
                    step = "grid cache bump"
                    self.bump()
            except Exception as e:
                if made and step == "season grid":
                    self._report(problems, f"#{num} rides for {tname} ({decision}) but no grid could be made "
                                           f"({type(e).__name__}: {e}); written on grid {gm[num]}: fix the team points by hand")
                    continue
                out[num] = gid
                self._report(problems, f"#{num} rides for {tname} ({decision}): written on grid {gid}, but the {step} "
                                       f"step failed ({type(e).__name__}: {e}); retried at the next session or run, "
                                       f"check grid {gid} by hand")
                continue
            out[num] = gid
            if made or fixed:
                what = f"new season grid {gid}" if made else f"grid {gid} completed ({', '.join(fixed)})"
                self._report(problems, f"#{num} rides for {tname} ({decision}): {what}"
                                       f"{', linked to team standing ' + str(desired) if desired else ', no team link'}, "
                                       f"in his driver standing, default photo. Add the photo and check the decision.")
            else:
                logger.info(f"#{num} rides for {tname} ({decision}): written on his grid {gid} (team standing {desired})")
        return out, problems

    @staticmethod
    def _ds_grids(d):
        a = d["attributes"]
        primary = ((a.get("seasonGrid") or {}).get("data") or {}).get("id")
        return [primary] + [g["id"] for g in ((a.get("grids") or {}).get("data") or []) if g["id"] != primary]

    def _create_grid(self, num, tname, target, season_id, gm, grids, team_of, rows):
        by_id = {g["id"]: g["attributes"] for g in grids}
        cur = by_id[gm[num]]
        mates = [n for n, t in rows if t == tname and n != num and team_of.get(gm.get(n)) == target and gm.get(n) in by_id]
        template = by_id[gm[mates[0]]] if mates else cur
        grid = self.strapi.post("season-grids", {
            "season": season_id, "driver": ((cur.get("driver") or {}).get("data") or {}).get("id"), "driverNumber": num,
            "chassis": ((template.get("chassis") or {}).get("data") or {}).get("id"), "teamColor": template.get("teamColor"),
            "driverPhoto": DEFAULT_PHOTO, "isOldGrid": True, "publishedAt": self.now_iso})
        return grid["id"]

    def _ensure_team(self, gid, desired, teams):
        """Add the grid to the team standing's grids (with retries). Returns the fixes made."""
        if desired is None:
            return []
        team = next(t for t in teams if t["id"] == desired)
        have = [g["id"] for g in team["attributes"]["seasonGrid"]["data"]]
        if gid in have:
            return []
        for attempt in range(3):
            try:
                self.strapi.put(f"team-standings/{desired}", {"seasonGrid": have + [gid]})
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(5)
        team["attributes"]["seasonGrid"]["data"].append({"id": gid})
        return ["team link"]

    def _ensure_driver(self, gid, mine, drivers):
        """Add the grid to the driver standing that counts one of his grids (mine). Returns the fixes made."""
        for d in drivers:
            ids = self._ds_grids(d)
            if mine & set(ids):
                if gid in ids:
                    return []
                self.strapi.put(f"driver-standings/{d['id']}", {"grids": ids + [gid]})
                d["attributes"].setdefault("grids", {"data": []})
                d["attributes"]["grids"] = {"data": [{"id": x} for x in ids + [gid]]}
                return ["driver standing"]
        raise RuntimeError(f"no driver standing counts his grids {sorted(mine)} yet (add grid {gid} to it when it is made)")


def make_handler():
    """Handler for the uploader: handler(year, gp_short, classification, grid_map) -> (grid_map, problems)."""
    from datetime import datetime, timezone
    from cron.data_upload.moto_gp.auto_grid import _bump_grid_cache
    from cron.data_upload.moto_gp.post_race import pulselive
    from cron.strapi_api.apis import get_headers
    from cron.utils import moto_graphql_end_point

    strapi = StrapiREST(moto_graphql_end_point.rsplit("/graphql", 1)[0], get_headers(False))
    check = TeamCheck(strapi, pulselive, None, _bump_grid_cache)

    def handler(year, gp_short, classification, grid_map):
        check.now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        return check.check(year, gp_short, classification, grid_map)

    return handler
