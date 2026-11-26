"""After a session is written: keep it equal to motogp.com, then send its results push, once.

Run by the weekend runner on every pass, for every session that started in the last FOLLOW_HOURS and has rows:

1. Sync. The session's Strapi rows (read uncached) are compared with motogp.com's current classification.
   Differences are rewritten: practice and qualifying position, time, laps, dnf and Q1 finalPos; Sprint and
   Race time and laps only (their order, points and dnf stay with the PDF-checked corrections.py), plus the
   Race fastest lap from the official record. Missing rows (a write that failed halfway) are created. A
   provisional copy coarser than what the app shows (a stale cache) is never written. motogp.com publishes a provisional
   classification first ("official": false, times rounded to 0.01 s) and the official one minutes later;
   both are followed, so the app always shows what motogp.com shows. Nothing is kept in memory that matters:
   after a runner handover the next run finds the same state in Strapi and in the feed.

2. Results push. Sent once per session (recorded on the motogp-state branch next to the reminders, so a
   handover or a second run never sends it twice), and only when the app shows exactly motogp.com's
   classification; the app's results cache key is bumped right before the send:
   - Practice and Q2: when the classification is official, or HOLD_MINUTES after the first write if
     motogp.com is still provisional then (so the push is never lost);
   - FP1 and FP2: on the quick version (no wait for "official");
   - Sprint and Race: at once (they are only written when every scoring rider has points);
   - and never within APP_CACHE_MINUTES of the last row change (the proxy cache in front of Strapi).
   A push that cannot go yet is retried on the next pass; nothing is announced over PUSH_LATE_MINUTES
   after the first write or PUSH_MAX_AGE_HOURS after the session start. No push after Q1 (the Q2 push covers qualifying). Paused by
   MOTOZ_SESSION_PUSH (not "on") and by control.json, like the reminders.

3. Stats. The derived stats are recomputed after the push (they take about a minute and do not change the
   results screen), for every Grand Prix written this pass by the ingest or by the sync.
"""
import json
from datetime import datetime, timedelta, timezone

from loguru import logger

FOLLOW_HOURS = 6
PUSH_MAX_AGE_HOURS = 24
# "Results are in" is news only right after they are: no push this long after the first write (a runner
# outage, a record that stayed unavailable). Covers the provisional hold and retries with a wide margin.
PUSH_LATE_MINUTES = 30
# Minutes a push waits for motogp.com's "official" classification (Ankur, 2026-11-20, as a user would want it):
# FP1/FP2 push on the quick version (nothing depends on their order); Practice ("who made Q2?") and Q2
# ("who took pole?") wait for it, since a lap deleted after the session can change exactly that.
HOLD_MINUTES = {"FP1": 0, "PRACTICE": 10, "FP2": 0, "QNR2": 10, "Sprint": 0, "Race": 0}
# The Strapi nginx proxy answers identical GraphQL queries (the app's too) from a cache for about 5 minutes.
# A push sent sooner after the last row change can open the app on the old answer, so it waits this long.
APP_CACHE_MINUTES = 6
# Keep the runner polling (every RUNNER_POLL_SECONDS) while a session may still change this soon after its write.
FAST_FOLLOW_MINUTES = 90
SYNC_FIELDS = ("position", "time", "laps", "dnf")  # finalPos: see plan_sync
SYNC_FIELDS_SC = ("time", "laps")


def _ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def _norm(field, value):
    if field == "time":
        return None if value in ("", None, "DNF") else value
    if field == "dnf":
        return bool(value)
    return value


def _decimals(t) -> int:
    t = _norm("time", t)
    return len(t.rsplit(".", 1)[1]) if t and "." in t else 0


def looks_stale(classification: list, rows: list, official: bool) -> bool:
    """A provisional classification with coarser times than the app already shows (official times are
    3 decimals, provisional 2): an old cached copy, never written over the official data."""
    if official:
        return False
    feed = max((_decimals(c.get("time") or (c.get("best_lap") or {}).get("time")) for c in classification), default=0)
    mine = max((_decimals(r.get("time")) for r in rows), default=0)
    return mine > feed


def plan_fastest_lap(classification: list, records: list, rows: list) -> list:
    """Race only, from the official classification: the fastestLap record's rider carries the flag, time
    and lap number, and no other row has the flag. (Sprint has no record; post_race takes it from the PDF.)"""
    rec = next((r for r in records or [] if r.get("type") == "fastestLap"), None)
    if not rec:
        return []
    num = next((c["rider"]["number"] for c in classification if c["rider"]["id"] == (rec.get("rider") or {}).get("id")), None)
    if num is None:
        return []
    lap = rec.get("bestLap") or {}
    want = {"fastestLap": True, "fastestLapTime": lap.get("time", ""), "fastestLapNo": lap.get("number", 0)}
    out = []
    for r in rows:
        if r["number"] == num:
            if any(r.get(k) != v for k, v in want.items()):
                out.append((r["id"], dict(want)))
        elif r.get("fastestLap"):
            out.append((r["id"], {"fastestLap": None, "fastestLapTime": None, "fastestLapNo": None}))
    return out


def plan_sync(race_type: str, classification: list, rows: list, fields_of):
    """Differences between the Strapi rows and the classification.
    fields_of(item, index, race_type) -> the Strapi fields of one classification row (uploader.result_fields).
    Returns (updates [(row_id, {field: new})], missing [classification items], extra [rider numbers])."""
    names = SYNC_FIELDS_SC if race_type in ("Sprint", "Race") else SYNC_FIELDS
    want = {c["rider"]["number"]: (c, fields_of(c, i, race_type)) for i, c in enumerate(classification)}
    have = {r["number"]: r for r in rows}
    updates = []
    for num, (_, f) in sorted(want.items(), key=lambda kv: kv[1][1]["position"]):
        r = have.get(num)
        if r is None:
            continue
        diff = {k: f.get(k) for k in names if _norm(k, f.get(k)) != _norm(k, r.get(k))}
        # finalPos (grid slot) is fixed later by post_race / audit_starting_grid from the FIM grid; rewriting it
        # here would undo those fixes. Only a Q1 rider whose Q1 position changes gets the new slot.
        if race_type == "QNR1" and "position" in diff:
            diff["finalPos"] = f.get("finalPos")
        if diff:
            updates.append((r["id"], diff))
    missing = [want[n][0] for n in want if n not in have]
    extra = sorted(n for n in have if n not in want)
    return updates, missing, extra


def duplicates(rows: list) -> list:
    seen, dup = set(), set()
    for r in rows:
        (dup if r["number"] in seen else seen).add(r["number"])
    return sorted(dup)


def push_decision(race_type: str, official: bool, equal: bool, first_write, start, now: datetime, last_write=None):
    """("send" | "wait" | "never", why). The results cache key is bumped right before every send, so the
    app refetches, and the send waits APP_CACHE_MINUTES after the last row change, so what it refetches
    through the proxy is the new data."""
    if now - start > timedelta(hours=PUSH_MAX_AGE_HOURS):
        return "never", f"started over {PUSH_MAX_AGE_HOURS} h ago"
    if first_write is not None and now - first_write > timedelta(minutes=PUSH_LATE_MINUTES):
        # Still news when the data only became right late inside the window (a handover gap): allow the push
        # until APP_CACHE_MINUTES + 5 after a last change made within PUSH_LATE_MINUTES of the first write.
        late_fix = last_write is not None and last_write - first_write <= timedelta(minutes=PUSH_LATE_MINUTES) \
            and now - last_write <= timedelta(minutes=APP_CACHE_MINUTES + 5)
        if not late_fix:
            return "never", f"written over {PUSH_LATE_MINUTES} min ago, no longer news"
    if not equal:
        return "wait", "the app does not show motogp.com's classification yet"
    if last_write is not None and now - last_write < timedelta(minutes=APP_CACHE_MINUTES):
        return "wait", f"last row change under {APP_CACHE_MINUTES} min ago (proxy cache)"
    if official:
        return "send", "official"
    hold = HOLD_MINUTES.get(race_type, 0)
    if first_write is not None and now - first_write >= timedelta(minutes=hold):
        return "send", f"still provisional {hold} min after the first write"
    return "wait", "provisional, waiting for the official classification"


def result_push_keys(race) -> list:
    from cron.notifiaction.moto_gp_session_reminders import session_key
    return [f"results:{race['id']}", f"results:{session_key(race)}"]


class Followup:
    """One instance per runner. `deps` holds every outside call, so tests run without network."""

    def __init__(self, deps, store, enabled: bool):
        self.d = deps
        self.store = store
        self.enabled = enabled
        self.session_uuid = {}  # race id -> motogp.com session uuid (a lookup cache only)
        self.done = set()       # race ids official, equal and announced (or never to be announced)
        self.logged = set()
        self.stats_retry = set()  # seasons whose stats recompute failed: retried every pass until it works
        self.bump_owed = set()    # Grand Prix whose cache key bump failed after a write: retried every pass
        self.missing_seen = {}    # race id -> rider numbers missing on the previous pass (create on the second)

    def _uuid(self, race):
        rid = str(race["id"])
        if not self.session_uuid.get(rid):
            self.session_uuid[rid] = self.d.session_uuid(race)  # a miss is not cached: looked up again next pass
        return self.session_uuid[rid]

    def _bump(self, gp_id):
        self.bump_owed.add(str(gp_id))
        self.d.bump_cache(gp_id)
        self.bump_owed.discard(str(gp_id))

    def run(self, now: datetime, stats_owed=None):
        """One pass. Returns (pending, problems). stats_owed: {year} of Grand Prix written by this pass's ingest."""
        stats_owed = set(stats_owed or ()) | self.stats_retry
        self.stats_retry = set(stats_owed)  # kept until the recompute below works, also if the lookup fails
        problems, pending = [], False
        for gp_id in sorted(self.bump_owed):
            try:
                self._bump(gp_id)
            except Exception as e:
                problems.append(f"GP {gp_id}: results cache key bump failed, retried next pass: {type(e).__name__}: {e}")
        races = self.d.races_between(now - timedelta(hours=FOLLOW_HOURS), now)
        for race in races:
            rid, rtype = str(race["id"]), race["attributes"]["type"]
            gp = race["attributes"]["grandPrix"]["data"]
            label = f'{gp["attributes"].get("shortName")} {rtype} (race {rid})'
            if rid in self.done or gp["attributes"].get("isCancelled") is True:
                continue
            try:
                p, wrote, probs = self._one(race, rid, rtype, gp, label, now)
            except Exception as e:
                logger.exception(f"{label}: results follow-up failed")
                p, wrote, probs = True, False, [f"{label}: results follow-up failed: {type(e).__name__}: {e}"]
                wrote = str(gp["id"]) in self.bump_owed  # rows were rewritten before the bump failed: stats owed too
            pending = pending or p
            problems += probs
            if wrote:
                stats_owed.add(str(gp["attributes"]["season"]["data"]["attributes"]["year"]))
        self.stats_retry = set(stats_owed)
        for year in sorted(stats_owed):
            try:
                self.d.update_stats(year)
                self.stats_retry.discard(year)
            except Exception as e:
                logger.exception(f"stats update failed for {year}")
                problems.append(f"stats update {year} failed (retried next pass): {type(e).__name__}: {e}")
        return pending, problems

    def _one(self, race, rid, rtype, gp, label, now):
        rows = self.d.session_rows(rid)
        if not rows:
            return False, False, []  # not written yet: the ingest owns it
        start = _ts(race["attributes"]["startTime"])
        first = min((_ts(r["createdAt"]) for r in rows if r.get("createdAt")), default=None)
        fresh = first is not None and now - first < timedelta(minutes=FAST_FOLLOW_MINUTES)
        uuid = self._uuid(race)
        if not uuid:
            return fresh, False, [f"{label}: session not found in the MotoGP API"]
        feed = self.d.classification(uuid)
        cls = feed.get("classification") or []
        official = bool(feed.get("official"))
        if not cls or self.d.points_missing(cls, rtype):
            return fresh, False, []  # feed empty or regressed for a moment: keep what is written, look again
        problems, wrote = [], False
        dup = duplicates(rows)
        if dup:
            problems.append(f"{label}: riders {dup} have two rows in the app (delete the extra row by hand)")
        stale = looks_stale(cls, rows, official)
        if stale:
            # The app already has official-precision times (corrections.py, from motogp.com's v1 feed) and this
            # copy is coarser: write nothing; the data counts as official, so the push is not held by it.
            updates, missing, extra = [], [], plan_sync(rtype, cls, rows, self.d.result_fields)[2]
            official = True
        else:
            updates, missing, extra = plan_sync(rtype, cls, rows, self.d.result_fields)
            if rtype == "Race" and official:
                updates += plan_fastest_lap(cls, feed.get("records"), rows)
        nums = sorted(m["rider"]["number"] for m in missing)
        if missing and not dup and self.missing_seen.get(rid) == nums:
            # Missing on two passes in a row: not a create of this pass's ingest still on its way.
            try:
                created = self.d.create_rows(race, missing, cls, rtype)  # raises on a missing season grid
            finally:
                problems += [f"{label}: {p}" for p in getattr(self.d, "take_problems", lambda: [])()]
            logger.info(f"{label}: created {created} missing rows")
            wrote = True
        self.missing_seen[rid] = nums
        if extra:
            problems.append(f"{label}: riders {extra} are in the app but not in motogp.com's classification (fix by hand)")
        for row_id, fields in updates:
            logger.info(f"{label} {'official' if official else 'provisional'} classification: row {row_id} {fields}")
            self.d.update_row(row_id, fields)
            wrote = True
        if wrote:
            self._bump(gp["id"])
            rows = self.d.session_rows(rid)
        if stale:
            equal = not dup and not extra and not plan_sync(rtype, cls, rows, self.d.result_fields)[1] and \
                not [u for u in plan_sync(rtype, cls, rows, self.d.result_fields)[0] if set(u[1]) - {"time"}]
        else:
            left, still_missing, still_extra = plan_sync(rtype, cls, rows, self.d.result_fields)  # what the app shows now
            if rtype == "Race" and official:
                left += plan_fastest_lap(cls, feed.get("records"), rows)
            equal = not left and not still_missing and not still_extra and not duplicates(rows)

        sent = self._push(race, rid, rtype, gp, label, now, start, official, equal, rows, problems)
        if official and equal and sent:
            self.done.add(rid)
        pending = fresh and not (official and equal and sent)
        return pending, wrote, problems

    def _push(self, race, rid, rtype, gp, label, now, start, official, equal, rows, problems) -> bool:
        """True when nothing is left to do for the push (sent, not wanted, or too old)."""
        from cron.notifiaction.moto_gp_session_reminders import RESULT_TYPES
        if rtype not in RESULT_TYPES:
            return True
        keys = result_push_keys(race)
        if any(k in self.store.sent or k in self.store.local for k in keys):
            return True
        first = min((_ts(r["createdAt"]) for r in rows if r.get("createdAt")), default=None)
        last = max((_ts(r["updatedAt"]) for r in rows if r.get("updatedAt")), default=None)
        decision, why = push_decision(rtype, official, equal, first, start, now, last)
        if decision == "never":
            if rid not in self.logged:
                self.logged.add(rid)
                # A new run's record is loaded only before a send: a push sent by the previous run is in the
                # shared record but not in memory yet (Portugal 2026: FP2 and Sprint pushes were sent, and the
                # next run reported them as NOT sent).
                try:
                    recorded = any(k in self.store.load() for k in keys)
                except Exception as e:
                    recorded = False
                    why = f"{why}; push record unavailable ({type(e).__name__}), it may have been sent by the previous run"
                if recorded:
                    return True
                logger.info(f"{label}: no results push ({why})")
                if first is not None and now - first < timedelta(minutes=PUSH_LATE_MINUTES + 30):
                    problems.append(f"{label}: results push NOT sent ({why}); check the run log")
            return True
        if decision == "wait":
            if (rid, why) not in self.logged:
                logger.info(f"{label}: results push waits: {why}")
                self.logged.add((rid, why))
            return False
        messages = self.d.result_messages(gp, rtype)
        if not self.enabled:
            if (rid, "dry") not in self.logged:
                logger.info(f"[results push dry run] would send {label}: {messages['en']}")
                self.logged.add((rid, "dry"))
            return True
        try:
            if any(k in self.store.load() for k in keys):  # re-check the shared record right before sending
                return True
            control = self.store.control()
        except Exception as e:
            problems.append(f"{label}: push record unavailable, results push retried next pass: {type(e).__name__}: {e}")
            return False
        raw = control.get("skip_race_ids") or []
        skip = {str(x).strip() for x in ([raw] if isinstance(raw, (str, int)) else raw)}
        if str(control.get("session_push", "on")).strip().lower() == "off" or rid in skip:
            if (rid, "paused") not in self.logged:
                logger.warning(f"{label}: results push paused by control.json")
                self.logged.add((rid, "paused"))
            return False  # still owed: sent if the pause ends while it is news
        try:
            self._bump(gp["id"])  # installed apps refetch this Grand Prix when the push is tapped
            self.d.send(messages)
        except Exception as e:
            problems.append(f"{label}: results push failed, retried next pass: {type(e).__name__}: {e}")
            return False
        logger.info(f"results push sent for {label} ({why}): {messages['en']}")
        try:
            self.store.mark(keys, now)
        except Exception as e:
            problems.append(f"{label}: results push sent but not recorded, a later run may resend: {type(e).__name__}: {e}")
        return True


class LiveDeps:
    """The real Strapi, MotoGP API and Firebase calls."""

    def __init__(self):
        self.problems = []  # from the team check of rows created here

    def take_problems(self):
        out, self.problems = self.problems, []
        return out

    def races_between(self, start, end):
        from cron.strapi_api.apis import get_races_starting_between
        iso = lambda dt: dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        return get_races_starting_between(False, iso(start), iso(end))

    def session_rows(self, race_id):
        from cron.strapi_api.apis import get_session_rows
        return get_session_rows(False, race_id)

    def session_uuid(self, race):
        from cron.moto_gp.moto_gp_api import fetch_season, fetch_event, fetch_session
        a = race["attributes"]["grandPrix"]["data"]["attributes"]
        season = fetch_season(str(a["season"]["data"]["attributes"]["year"]))
        event = fetch_event(event_name=a["shortName"], season_uuid=season)
        return fetch_session(session_type=race["attributes"]["type"], event_uuid=event)

    def classification(self, uuid):
        from cron.moto_gp.moto_gp_api import fetch_race_results
        return fetch_race_results(uuid)

    def points_missing(self, cls, rtype):
        from cron.data_upload.moto_gp.moto_gp_data_upload import points_missing
        return points_missing(cls, rtype)

    def result_fields(self, item, index, rtype):
        from cron.data_upload.moto_gp.moto_gp_data_upload import result_fields
        return result_fields(item, index, rtype)

    def create_rows(self, race, missing, cls, rtype):
        from cron.data_upload.moto_gp.moto_gp_data_upload import result_fields, MissingSeasonGridError
        from cron.strapi_api.apis import get_season_grid_map, create_race_result
        year = str(race["attributes"]["grandPrix"]["data"]["attributes"]["season"]["data"]["attributes"]["year"])
        grid = get_season_grid_map(is_f1_feed=False, season=year, fill_from_old_grids=True)
        nums = sorted({m["rider"]["number"] for m in missing if m["rider"]["number"] not in grid})
        if nums:
            raise MissingSeasonGridError(nums)
        from cron.data_upload.moto_gp.moto_gp_data_upload import team_checked
        gp_short = race["attributes"]["grandPrix"]["data"]["attributes"]["shortName"]
        grid = team_checked(year, gp_short, cls, grid, sink=self.problems)  # same team rule as the ingest
        index = {id(c): i for i, c in enumerate(cls)}
        for m in missing:
            body = {"race": str(race["id"]), "seasonGrid": grid[m["rider"]["number"]], **result_fields(m, index[id(m)], rtype)}
            create_race_result(is_f1_feed=False, json_str=json.dumps(body))
        return len(missing)

    def update_row(self, row_id, fields):
        from cron.strapi_api.apis import update_race_result
        update_race_result(is_f1_feed=False, json_str=json.dumps(fields), row_id=row_id)

    def bump_cache(self, gp_id):
        from cron.strapi_api.apis import update_config_for_race_result
        update_config_for_race_result(is_f1_feed=False, gp_id=gp_id, strict=True)

    def result_messages(self, gp, rtype):
        from cron.notifiaction.moto_gp_session_reminders import build_result_messages
        return build_result_messages(gp, rtype)

    def send(self, messages):
        from cron.notifiaction.notification_utils import send_localized_notification_to_topic
        send_localized_notification_to_topic(is_f1=False, is_prod=True, messages=messages)

    def update_stats(self, year):
        from cron.stats_calc.moto_gp.moto_gp_stats_update import process_update_moto_gp_stats
        process_update_moto_gp_stats(season_year=year)
