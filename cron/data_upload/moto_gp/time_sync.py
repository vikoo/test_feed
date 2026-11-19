"""Keep upcoming session times in Strapi equal to the official motogp.com timetable.

Qatar 2026: MotoGP moved the whole timetable 1 hour earlier two days before the weekend; Strapi kept the old
times and the app showed every session 1 hour late. This pass, run at the start of every race-result run,
compares each session starting in the next 8 days with the official timetable and writes the official time
when they differ by 5 minutes or more.

Same-day delays are not written (mz-ops LEARNINGS.md: keep the planned time in Strapi): a session is only
changed when both the Strapi and the official start are more than 6 hours away. The GP window (startDate,
endDate) follows the first session and the Race, and the calendar cache is bumped so the app refetches.
"""
from datetime import datetime, timedelta, timezone

from loguru import logger

LOOKAHEAD = timedelta(days=8)
MIN_LEAD = timedelta(hours=6)
MISMATCH = timedelta(minutes=5)
MIN_RACE_TO_END = timedelta(minutes=45)
# A real timetable change moves a session by hours (Qatar 2026: 1 h). More than this means a wrong event
# link (siteEventId) or a wrong date in Strapi: held and reported, never written.
MAX_MOVE = timedelta(days=2)


def _dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def plan(races: list, official_for, now: datetime, held=None):
    """races: Strapi races (with grandPrix id, siteEventId, startDate, endDate). official_for(site_event_id) ->
    {session type: official start} (cancelled sessions left out). Returns (session_changes [(race, old, new)],
    gp_changes {gp_id: fields}). Moves larger than MAX_MOVE are appended to `held` (strings), not planned."""
    changes, gp_changes = [], {}
    held = held if held is not None else []
    by_gp = {}
    for r in races:
        g = (r["attributes"].get("grandPrix") or {}).get("data")
        if g:
            by_gp.setdefault(g["id"], (g, []))[1].append(r)
    for gp_id, (g, rs) in by_gp.items():
        ga = g["attributes"]
        if ga.get("isCancelled") is True or not ga.get("siteEventId"):
            continue
        official = official_for(ga["siteEventId"]) or {}
        new_start = {}
        for r in rs:
            t = r["attributes"]["type"]
            mine, off = _dt(r["attributes"]["startTime"]), official.get(t)
            if not off or abs(off - mine) < MISMATCH:
                continue
            if mine - now <= MIN_LEAD or off - now <= MIN_LEAD:
                logger.info(f"race {r['id']} {t}: official {off} differs but is too close, left as planned")
                continue
            if abs(off - mine) > MAX_MOVE:
                held.append(f"race {r['id']} {t}: official start {off:%a %d %b %H:%M} UTC is more than "
                            f"{MAX_MOVE.days} days from Strapi {mine:%a %d %b %H:%M} UTC; not changed, check the event link")
                continue
            changes.append((r, mine, off))
            new_start[t] = (mine, off)
        # GP window. 2026 data has no single convention (endDate is 45 to 240 min after the Race, a few
        # startDates are before FP1), so keep each GP's own gap, but never let the window cut a session off.
        fields = {}
        if "FP1" in new_start and ga.get("startDate"):
            old_fp1, new_fp1 = new_start["FP1"]
            cur = _dt(ga["startDate"])
            if cur == old_fp1 or cur > new_fp1:
                fields["startDate"] = _iso(new_fp1)
        if "Race" in new_start and ga.get("endDate"):
            old_race, new_race = new_start["Race"]
            gap = max(_dt(ga["endDate"]) - old_race, MIN_RACE_TO_END)  # Qatar had endDate before the Race
            fields["endDate"] = _iso(new_race + gap)
        if fields:
            gp_changes[gp_id] = fields
    return changes, gp_changes


def make_pass(min_interval=timedelta(hours=1)):
    """Bound to Strapi and the official timetable. Returns pass(now) -> problems (list)."""
    import requests
    from cron.notifiaction.moto_gp_session_reminders import fetch_official_sessions
    from cron.strapi_api.apis import get_races_starting_between, update_config_for_gp, get_headers
    from cron.utils import moto_graphql_end_point

    state = {"last": None}
    base = moto_graphql_end_point.rsplit("/graphql", 1)[0]

    def official_for(site_event_id):
        return {t: v["start"] for t, v in fetch_official_sessions(site_event_id).items() if v.get("status") != "CANCELLED"}

    def put(path, fields):
        r = requests.put(f"{base}/api/{path}", json={"data": fields}, headers=get_headers(False), timeout=30)
        r.raise_for_status()

    def run(now: datetime):
        if state["last"] and now - state["last"] < min_interval:
            return []
        state["last"] = now
        problems = []
        try:
            races = get_races_starting_between(False, _iso(now), _iso(now + LOOKAHEAD))
            changes, gp_changes = plan(races, official_for, now, problems)
        except Exception as e:
            return [f"session time check failed: {type(e).__name__}: {e}"]
        failed_gps = set()
        for r, old, new in changes:
            try:
                put(f"races/{r['id']}", {"startTime": _iso(new)})  # only the time: siteEventId stays as it is
                logger.warning(f"session time fixed from the official timetable: race {r['id']} "
                               f"{r['attributes']['type']} {old:%a %d %b %H:%M} -> {new:%a %d %b %H:%M} UTC")
            except Exception as e:
                failed_gps.add(((r["attributes"].get("grandPrix") or {}).get("data") or {}).get("id"))
                problems.append(f"race {r['id']} {r['attributes']['type']}: time fix {old} -> {new} failed: "
                                f"{type(e).__name__}: {e}")
        for gp_id, fields in gp_changes.items():
            if gp_id in failed_gps:
                continue  # window follows the sessions only once they are written (no drift on the retry)
            try:
                put(f"grand-prixes/{gp_id}", fields)
                logger.warning(f"GP {gp_id} window updated: {fields}")
            except Exception as e:
                problems.append(f"GP {gp_id}: window update {fields} failed: {type(e).__name__}: {e}")
        if changes or gp_changes:
            state["last"] = None if failed_gps else now  # retry a failed write on the next pass, not in 1 h
            update_config_for_gp(is_f1_feed=False)  # calendar cache: the app refetches the schedule
        return problems

    return run
