"""Results follow-up: the app stays equal to motogp.com and every session gets its results push once.

Built after Portugal FP1 2026: written 11:36 UTC from a provisional classification (times rounded to 0.01 s),
official about 11:43 UTC, full times in the app only at 11:58 UTC; the results push was held by a cached
read-back ("0 of 22 rows") and never retried.
"""
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from loguru import logger

from cron.data_upload.moto_gp import moto_gp_data_upload as up
from cron.data_upload.moto_gp import results_followup as rf
from cron.data_upload.moto_gp import weekend_runner as wr

FIX = json.load(open(os.path.join(os.path.dirname(__file__), "testdata", "portugal_fp1_2026.json")))
T0 = datetime(2026, 11, 20, 11, 36, 26, tzinfo=timezone.utc)  # first FP1 write


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def race(rid="600", rtype="FP1", start="2026-11-20T10:45:00.000Z", gp_id="63", event="c7f7626b", cancelled=None):
    return {"id": rid, "attributes": {"type": rtype, "startTime": start, "grandPrix": {"data": {"id": gp_id, "attributes": {
        "name": "PORTUGAL GP 26", "shortName": "POR", "siteEventId": event, "isCancelled": cancelled,
        "season": {"data": {"attributes": {"year": "2026"}}}}}}}}


def item(num, pos, lap="", laps=18, points=None, time=None, status="INSTND"):
    c = {"position": pos, "rider": {"number": num, "id": f"r{num}"}, "best_lap": {"number": 9, "time": lap} if lap else None,
         "total_laps": laps, "status": status}
    if points is not None:
        c["points"] = points
    if time is not None:
        c["time"] = time
    return c


class FakeStore:
    def __init__(self, remote=None, fail_load=False, control=None):
        self.remote = dict(remote or {}); self.sent = {}; self.local = {}
        self.fail_load = fail_load; self._control = control or {}; self.marks = []

    def load(self):
        if self.fail_load:
            raise RuntimeError("GitHub 502")
        self.sent = {**self.remote, **self.local}
        return self.sent

    def control(self):
        return self._control

    def mark(self, keys, when):
        self.marks.append(list(keys))
        for k in keys:
            self.local[k] = when.isoformat(); self.remote[k] = when.isoformat()
        self.sent = {**self.sent, **self.local}


class FakeDeps:
    """Strapi rows and the motogp.com feed in memory; records every write, bump, push and stats run."""

    def __init__(self, races, feeds, rows=None, created_at=T0):
        self.races = races; self.feeds = feeds  # race id -> feed dict
        self.rows = rows or {}                   # race id -> [row dicts]
        self.created_at = created_at
        self.log = []; self.send_fail = 0; self.stats_fail = False
        self.grid = {n: f"g{n}" for n in range(1, 100)}

    def write_session(self, rid, cls, rtype):
        self.rows[rid] = [{"id": f"{rid}-{c['rider']['number']}", "number": c["rider"]["number"],
                           "createdAt": iso(self.created_at), "updatedAt": iso(self.created_at),
                           **up.result_fields(c, i, rtype)} for i, c in enumerate(cls)]

    # LiveDeps interface
    def races_between(self, start, end):
        self.now = end
        return [r for r in self.races if start <= datetime.fromisoformat(r["attributes"]["startTime"].replace("Z", "+00:00")) <= end]

    def session_rows(self, rid):
        return [dict(r) for r in self.rows.get(rid, [])]

    def session_uuid(self, r):
        return f"uuid-{r['id']}"

    def classification(self, uuid):
        return self.feeds[uuid.split("-", 1)[1]]

    def points_missing(self, cls, rtype):
        return up.points_missing(cls, rtype)

    def result_fields(self, c, i, rtype):
        return up.result_fields(c, i, rtype)

    def create_rows(self, r, missing, cls, rtype):
        idx = {id(c): i for i, c in enumerate(cls)}
        for m in missing:
            self.rows[r["id"]].append({"id": f"{r['id']}-{m['rider']['number']}", "number": m["rider"]["number"],
                                       "createdAt": iso(self.now), "updatedAt": iso(self.now),
                                       **up.result_fields(m, idx[id(m)], rtype)})
            self.log.append(("create", r["id"], m["rider"]["number"]))
        return len(missing)

    def update_row(self, row_id, fields):
        rid = row_id.split("-")[0]
        for row in self.rows[rid]:
            if row["id"] == row_id:
                row.update(fields); row["updatedAt"] = iso(self.now)
        self.log.append(("update", row_id, fields))

    def bump_cache(self, gp_id):
        self.log.append(("bump", gp_id))

    def result_messages(self, gp, rtype):
        from cron.notifiaction.moto_gp_session_reminders import build_result_messages
        return build_result_messages(gp, rtype)

    def send(self, messages):
        if self.send_fail:
            self.send_fail -= 1
            raise RuntimeError("FCM 503")
        self.log.append(("push", messages["en"][0]))

    def update_stats(self, year):
        if self.stats_fail:
            raise RuntimeError("stats down")
        self.log.append(("stats", year))

    def kinds(self, kind):
        return [x for x in self.log if x[0] == kind]


class Base(unittest.TestCase):
    def setUp(self):
        logger.remove()

    def follow(self, deps, store=None, enabled=True):
        return rf.Followup(deps, store if store is not None else FakeStore(), enabled)


M = lambda m: T0 + timedelta(minutes=m)


class PortugalFp1ReplayTest(Base):
    """Today's FP1, minute by minute, with the real motogp.com classifications."""

    def test_provisional_then_official(self):
        """Practice waits for the official classification (FP1's real feeds, replayed as Practice)."""
        deps = FakeDeps([race("601", "PRACTICE")], {"601": FIX["provisional"]})
        deps.rows = {}
        deps.write_session("601", FIX["provisional"]["classification"], "PRACTICE")
        store = FakeStore()
        f = self.follow(deps, store)
        # 11:37: provisional, equal to the app: no push yet (Practice waits for the official times)
        pending, problems = f.run(M(1))
        self.assertTrue(pending); self.assertEqual(problems, []); self.assertEqual(deps.kinds("push"), [])
        # 11:43: official. All 22 times rewritten at once and the cache bumped; the push waits out the proxy cache
        deps.feeds["601"] = FIX["official"]
        pending, problems = f.run(M(7))
        updates = deps.kinds("update")
        self.assertEqual(len(updates), 22)
        self.assertEqual({tuple(u[2]) for u in updates}, {("time",)})
        self.assertIn(("update", "601-72", {"time": "01:39.002"}), updates)
        self.assertEqual(deps.kinds("push"), []); self.assertTrue(pending)
        f.run(M(12)); self.assertEqual(deps.kinds("push"), [])
        # 11:49: six minutes after the last change: cache bumped again and the push sent, once
        pending, problems = f.run(M(13))
        self.assertEqual(deps.kinds("push"), [("push", "📊 Portugal GP: Practice")])
        self.assertEqual(deps.log[-1][0], "push"); self.assertEqual(deps.log[-2][0], "bump")
        self.assertFalse(pending); self.assertEqual(problems, [])
        self.assertEqual(store.marks, [["results:601", "results:c7f7626b:PRACTICE"]])
        n = len(deps.log)
        f.run(M(15)); f.run(M(29))
        self.assertEqual(len(deps.log), n)

    def test_already_official_at_the_first_write(self):
        deps = FakeDeps([race()], {"600": FIX["official"]})
        deps.write_session("600", FIX["official"]["classification"], "FP1")
        f = self.follow(deps)
        f.run(M(1)); f.run(M(5)); self.assertEqual(deps.kinds("push"), [])
        f.run(M(6)); self.assertEqual(len(deps.kinds("push")), 1); self.assertEqual(deps.kinds("update"), [])

    def test_still_provisional_after_the_hold_is_announced_anyway(self):
        deps = FakeDeps([race("601", "PRACTICE")], {"601": FIX["provisional"]})
        deps.write_session("601", FIX["provisional"]["classification"], "PRACTICE")
        f = self.follow(deps)
        f.run(M(9)); self.assertEqual(deps.kinds("push"), [])
        f.run(M(10)); self.assertEqual(len(deps.kinds("push")), 1)
        deps.feeds["601"] = FIX["official"]
        f.run(M(20))  # official later: times rewritten, no second push
        self.assertEqual(len(deps.kinds("update")), 22); self.assertEqual(len(deps.kinds("push")), 1)

    def test_fp1_and_fp2_push_on_the_quick_version(self):
        """FP1/FP2 (Ankur, 2026-11-20): no wait for "official", only the 6 min proxy-cache wait."""
        for rid, rtype in (("600", "FP1"), ("602", "FP2")):
            deps = FakeDeps([race(rid, rtype)], {rid: FIX["provisional"]})
            deps.rows = {}
            deps.write_session(rid, FIX["provisional"]["classification"], rtype)
            f = self.follow(deps)
            f.run(M(5)); self.assertEqual(deps.kinds("push"), [], rtype)
            f.run(M(6)); self.assertEqual(len(deps.kinds("push")), 1, rtype)
            deps.feeds[rid] = FIX["official"]
            f.run(M(8))  # official later: all 22 times rewritten, no second push
            self.assertEqual(len(deps.kinds("update")), 22, rtype); self.assertEqual(len(deps.kinds("push")), 1, rtype)

    def test_practice_and_q2_still_wait_for_official(self):
        for rtype in ("PRACTICE", "QNR2"):
            deps = FakeDeps([race("601", rtype)], {"601": FIX["provisional"]})
            deps.rows = {}
            deps.write_session("601", FIX["provisional"]["classification"], rtype)
            f = self.follow(deps)
            f.run(M(6)); f.run(M(9)); self.assertEqual(deps.kinds("push"), [], rtype)
            f.run(M(10)); self.assertEqual(len(deps.kinds("push")), 1, rtype)

    def test_stale_provisional_copy_never_overwrites_official_times(self):
        deps = FakeDeps([race()], {"600": FIX["official"]})
        deps.write_session("600", FIX["official"]["classification"], "FP1")
        deps.feeds["600"] = FIX["provisional"]  # an old CDN copy served after the official one
        pending, problems = self.follow(deps).run(M(8))
        self.assertEqual(deps.kinds("update"), [])  # never rounded back down
        self.assertEqual(len(deps.kinds("push")), 1)  # and the push is not held by the old copy
        self.assertEqual(problems, [])


class PushOnceTest(Base):
    def setup_fp1(self):
        deps = FakeDeps([race()], {"600": FIX["official"]})
        deps.write_session("600", FIX["official"]["classification"], "FP1")
        return deps

    def test_failed_send_is_retried_next_pass(self):
        deps = self.setup_fp1(); deps.send_fail = 1
        f = self.follow(deps)
        pending, problems = f.run(M(6))
        self.assertTrue(pending); self.assertIn("results push failed, retried next pass", problems[0])
        pending, problems = f.run(M(7))
        self.assertEqual(len(deps.kinds("push")), 1); self.assertFalse(pending)

    def test_new_run_after_a_handover_does_not_resend(self):
        deps = self.setup_fp1(); store = FakeStore()
        self.follow(deps, store).run(M(6))
        fresh = FakeStore(remote=store.remote)  # the next run starts with an empty memory
        self.follow(deps, fresh).run(M(8))
        self.assertEqual(len(deps.kinds("push")), 1)

    def test_record_unavailable_sends_nothing_and_retries(self):
        deps = self.setup_fp1(); store = FakeStore(fail_load=True)
        f = self.follow(deps, store)
        pending, problems = f.run(M(6))
        self.assertEqual(deps.kinds("push"), []); self.assertTrue(pending); self.assertIn("push record unavailable", problems[0])
        store.fail_load = False
        f.run(M(7)); self.assertEqual(len(deps.kinds("push")), 1)

    def test_duplicated_strapi_session_row_gets_one_push(self):
        deps = FakeDeps([race("600"), race("700")], {"600": FIX["official"], "700": FIX["official"]})
        deps.write_session("600", FIX["official"]["classification"], "FP1")
        deps.write_session("700", FIX["official"]["classification"], "FP1")
        self.follow(deps).run(M(6))
        self.assertEqual(len(deps.kinds("push")), 1)  # same official event and session type

    def test_paused_dry_run_and_old_sessions_send_nothing(self):
        deps = self.setup_fp1()
        self.follow(deps, FakeStore(control={"session_push": "off"})).run(M(6))
        self.follow(deps, FakeStore(control={"skip_race_ids": ["600"]})).run(M(6))
        self.follow(deps, enabled=False).run(M(6))
        self.assertEqual(deps.kinds("push"), [])

    def test_no_push_half_an_hour_after_the_write(self):
        """Deploying this today must not announce Portugal FP1 (written 11:36 UTC) late."""
        deps = self.setup_fp1(); store = FakeStore()
        pending, problems = self.follow(deps, store).run(M(31))
        self.assertEqual(deps.kinds("push"), []); self.assertEqual(store.marks, [])
        self.assertIn("results push NOT sent", problems[0])  # a near miss turns the run red
        quiet = self.setup_fp1()
        self.assertEqual(self.follow(quiet).run(M(70)), (False, []))  # today's FP1 at deploy time: no noise
        d2 = self.setup_fp1(); self.follow(d2).run(M(29)); self.assertEqual(len(d2.kinds("push")), 1)

    def test_push_sent_by_the_previous_run_is_no_alarm(self):
        """Portugal 2026: FP2 push sent 10:55 by one run; the next run (11:14) reported it as NOT sent."""
        deps = self.setup_fp1()
        store = FakeStore(remote={"results:600": "2026-11-20T11:42:00+00:00"})  # in the record, not in memory
        self.assertEqual(store.sent, {})
        pending, problems = self.follow(deps, store).run(M(31))
        self.assertEqual((deps.kinds("push"), problems), ([], []))

    def test_record_unreadable_near_miss_still_alarms(self):
        deps = self.setup_fp1()
        pending, problems = self.follow(deps, FakeStore(fail_load=True)).run(M(31))
        self.assertEqual(deps.kinds("push"), [])
        self.assertIn("results push NOT sent", problems[0]); self.assertIn("push record unavailable", problems[0])

    def test_q1_has_no_push_q2_has_one(self):
        q1 = [item(1, 1, "01:38.101"), item(2, 2, "01:38.202"), item(3, 3, "01:38.303")]
        deps = FakeDeps([race("603", "QNR1", "2026-11-21T10:50:00.000Z"), race("604", "QNR2", "2026-11-21T11:15:00.000Z")],
                        {"603": {"official": True, "classification": q1}, "604": {"official": True, "classification": q1}},
                        created_at=datetime(2026, 11, 21, 11, 33, tzinfo=timezone.utc))
        deps.write_session("603", q1, "QNR1"); deps.write_session("604", q1, "QNR2")
        self.follow(deps).run(datetime(2026, 11, 21, 11, 40, tzinfo=timezone.utc))
        self.assertEqual(deps.kinds("push"), [("push", "🏁 Portugal GP: Grid is set")])

    def test_cancelled_grand_prix_is_skipped(self):
        deps = FakeDeps([race(cancelled=True)], {"600": FIX["official"]})
        deps.write_session("600", FIX["official"]["classification"], "FP1")
        self.assertEqual(self.follow(deps).run(M(6)), (False, [])); self.assertEqual(deps.log, [])


class SyncTest(Base):
    def test_cancelled_lap_reorders_practice(self):
        prov = [item(72, 1, "1:39.00"), item(89, 2, "1:39.14"), item(73, 3, "1:39.24")]
        off = [item(89, 1, "01:39.144"), item(72, 2, "01:39.201"), item(73, 3, "01:39.245")]
        w = datetime(2026, 11, 20, 16, 3, tzinfo=timezone.utc)
        deps = FakeDeps([race("601", "PRACTICE", "2026-11-20T15:00:00.000Z")], {"601": {"official": True, "classification": off}}, created_at=w)
        deps.write_session("601", prov, "PRACTICE")
        f = self.follow(deps)
        f.run(w + timedelta(minutes=2))
        rows = {r["number"]: r for r in deps.rows["601"]}
        self.assertEqual((rows[89]["position"], rows[72]["position"], rows[72]["time"]), (1, 2, "01:39.201"))
        f.run(w + timedelta(minutes=8)); self.assertEqual(len(deps.kinds("push")), 1)

    def test_q1_final_pos_follows_the_official_order(self):
        prov = [item(1, 1, "1:38.10"), item(2, 2, "1:38.20"), item(3, 3, "1:38.30")]
        off = [item(1, 1, "01:38.101"), item(3, 2, "01:38.199"), item(2, 3, "01:38.201")]
        w = datetime(2026, 11, 21, 11, 8, tzinfo=timezone.utc)
        deps = FakeDeps([race("603", "QNR1", "2026-11-21T10:50:00.000Z")], {"603": {"official": True, "classification": off}}, created_at=w)
        deps.write_session("603", prov, "QNR1")
        self.follow(deps).run(w + timedelta(minutes=2))
        rows = {r["number"]: r for r in deps.rows["603"]}
        self.assertEqual((rows[3]["position"], rows[3]["finalPos"], rows[2]["position"], rows[2]["finalPos"]), (2, None, 3, 13))

    def race_case(self, prov, official_feed, w):
        deps = FakeDeps([race("606", "Race", "2026-11-22T13:00:00.000Z")], {"606": {"official": False, "classification": prov}}, created_at=w)
        deps.write_session("606", prov, "Race")
        return deps

    def test_race_pushed_without_waiting_for_official_order_points_dnf_stay_with_the_pdf_check(self):
        prov = [item(72, 1, laps=25, points=25, time="41:02.11"), item(89, 2, laps=25, points=20, time="+1.20"),
                item(73, None, laps=3, points=0, status="OUTSTND")]
        off = [item(89, 1, laps=25, points=25, time="41:02.115"), item(72, 2, laps=25, points=20, time="+1.203"),
               item(73, None, laps=4, points=0, status="OUTSTND")]
        w = datetime(2026, 11, 22, 13, 44, tzinfo=timezone.utc)
        deps = self.race_case(prov, off, w)
        f = self.follow(deps)
        f.run(w + timedelta(minutes=6))
        self.assertEqual(deps.kinds("push"), [("push", "🏆 Portugal GP: Race results")])  # Race: no wait for "official"
        deps.feeds["606"] = {"official": True, "classification": off}
        f.run(w + timedelta(minutes=8))
        rows = {r["number"]: r for r in deps.rows["606"]}
        self.assertEqual((rows[72]["position"], rows[72]["time"], rows[72]["points"]), (1, "+1.203", 25))
        self.assertEqual(rows[73]["laps"], 4)
        self.assertEqual({k for u in deps.kinds("update") for k in u[2]}, {"time", "laps"})
        self.assertEqual(len(deps.kinds("push")), 1)

    def test_race_fastest_lap_follows_the_official_record(self):
        cls = [item(72, 1, laps=25, points=25, time="41:02.115"), item(89, 2, laps=25, points=20, time="+1.203")]
        w = datetime(2026, 11, 22, 13, 44, tzinfo=timezone.utc)
        deps = self.race_case(cls, None, w)
        deps.rows["606"][0].update(fastestLap=True, fastestLapTime="01:39.80", fastestLapNo=5)  # provisional record
        deps.feeds["606"] = {"official": True, "classification": cls, "records": [
            {"type": "fastestLap", "rider": {"id": "r89"}, "bestLap": {"number": 7, "time": "01:39.812"}}]}
        self.follow(deps).run(w + timedelta(minutes=2))
        rows = {r["number"]: r for r in deps.rows["606"]}
        self.assertEqual((rows[89]["fastestLap"], rows[89]["fastestLapTime"], rows[89]["fastestLapNo"]), (True, "01:39.812", 7))
        self.assertEqual((rows[72]["fastestLap"], rows[72]["fastestLapTime"]), (None, None))

    def test_dnf_time_forms_are_equal(self):
        cls = [item(72, 1, laps=25, points=25, time="41:02.115"), item(73, None, laps=3, points=0, status="OUTSTND")]
        w = datetime(2026, 11, 22, 13, 44, tzinfo=timezone.utc)
        deps = FakeDeps([race("606", "Race", "2026-11-22T13:00:00.000Z")], {"606": {"official": True, "classification": cls}}, created_at=w)
        deps.write_session("606", cls, "Race")
        deps.rows["606"][1]["time"] = None  # corrections.py writes None where the API has no time
        self.follow(deps).run(w + timedelta(minutes=1))
        self.assertEqual(deps.kinds("update"), [])

    def test_half_written_practice_is_completed_then_announced(self):
        deps = FakeDeps([race()], {"600": FIX["official"]})
        deps.write_session("600", FIX["official"]["classification"], "FP1")
        deps.rows["600"] = deps.rows["600"][:11]  # the ingest failed after 11 of 22 rows
        f = self.follow(deps)
        f.run(M(1)); self.assertEqual(deps.kinds("create"), [])  # first sighting: maybe the ingest's own write in flight
        f.run(M(2))
        self.assertEqual(len(deps.kinds("create")), 11); self.assertEqual(len(deps.rows["600"]), 22)
        f.run(M(7)); self.assertEqual(deps.kinds("push"), [])  # 5 min after the repair: proxy cache
        f.run(M(8)); self.assertEqual(len(deps.kinds("push")), 1)

    def test_half_written_sprint_is_completed(self):
        cls = [item(72, 1, laps=11, points=12, time="18:46.450"), item(89, 2, laps=11, points=9, time="+0.812")]
        w = datetime(2026, 11, 21, 15, 29, tzinfo=timezone.utc)
        deps = FakeDeps([race("605", "Sprint", "2026-11-21T15:00:00.000Z")], {"605": {"official": True, "classification": cls}}, created_at=w)
        deps.write_session("605", cls[:1], "Sprint")
        f = self.follow(deps)
        f.run(w + timedelta(minutes=1)); f.run(w + timedelta(minutes=2))
        self.assertEqual(deps.kinds("create"), [("create", "605", 89)])
        self.assertEqual({r["number"]: r["points"] for r in deps.rows["605"]}, {72: 12, 89: 9})
        f.run(w + timedelta(minutes=8)); self.assertEqual(len(deps.kinds("push")), 1)

    def test_duplicate_rows_are_reported_never_announced_never_extended(self):
        deps = FakeDeps([race()], {"600": FIX["official"]})
        deps.write_session("600", FIX["official"]["classification"], "FP1")
        deps.rows["600"].append(dict(deps.rows["600"][0], id="600-72b"))  # 23 rows for 22 riders
        deps.rows["600"] = [r for r in deps.rows["600"] if r["number"] != 89]
        f = self.follow(deps)
        for m in (6, 7, 8):
            pending, problems = f.run(M(m))
        self.assertEqual(deps.kinds("push"), []); self.assertEqual(deps.kinds("create"), [])
        self.assertIn("riders [72] have two rows", problems[0])

    def test_handover_gap_still_announces_data_fixed_late_in_the_window(self):
        deps = FakeDeps([race()], {"600": FIX["official"]})
        deps.write_session("600", FIX["provisional"]["classification"], "FP1")
        self.follow(deps).run(M(25))  # the new run starts 25 min after the write: official times written now
        f = self.follow(deps)
        f.run(M(30)); self.assertEqual(deps.kinds("push"), [])
        f.run(M(31)); self.assertEqual(len(deps.kinds("push")), 1)  # 6 min after the fix, past the 30 min mark

    def test_grid_slot_fixed_by_post_race_is_left_alone(self):
        q2 = [item(1, 1, "01:38.101"), item(2, 2, "01:38.202")]
        w = datetime(2026, 11, 21, 11, 33, tzinfo=timezone.utc)
        deps = FakeDeps([race("604", "QNR2", "2026-11-21T11:15:00.000Z")], {"604": {"official": True, "classification": q2}}, created_at=w)
        deps.write_session("604", q2, "QNR2")
        deps.rows["604"][1]["finalPos"] = 17  # grid penalty applied from the FIM grid
        self.follow(deps).run(w + timedelta(minutes=7))
        self.assertEqual(deps.kinds("update"), []); self.assertEqual(deps.rows["604"][1]["finalPos"], 17)

    def test_pause_keeps_the_push_owed(self):
        deps = FakeDeps([race()], {"600": FIX["official"]})
        deps.write_session("600", FIX["official"]["classification"], "FP1")
        store = FakeStore(control={"session_push": "off"})
        f = self.follow(deps, store)
        f.run(M(6)); self.assertEqual(deps.kinds("push"), [])
        store._control = {}
        f.run(M(9)); self.assertEqual(len(deps.kinds("push")), 1)

    def test_rider_only_in_the_app_is_reported_and_not_announced(self):
        deps = FakeDeps([race()], {"600": FIX["official"]})
        deps.write_session("600", FIX["official"]["classification"], "FP1")
        deps.rows["600"].append({**deps.rows["600"][0], "id": "600-99", "number": 99})
        pending, problems = self.follow(deps).run(M(7))
        self.assertEqual(deps.kinds("push"), []); self.assertIn("riders [99]", problems[0])

    def test_feed_regressing_to_missing_points_changes_nothing(self):
        cls = [item(72, 1, laps=25, points=25, time="41:02.115"), item(89, 2, laps=25, points=20, time="+1.203")]
        w = datetime(2026, 11, 22, 13, 44, tzinfo=timezone.utc)
        deps = FakeDeps([race("606", "Race", "2026-11-22T13:00:00.000Z")], {"606": {"official": True, "classification": cls}}, created_at=w)
        deps.write_session("606", cls, "Race")
        deps.feeds["606"] = {"official": False, "classification": [dict(c, points=None) for c in cls]}
        pending, problems = self.follow(deps).run(w + timedelta(minutes=7))
        self.assertTrue(pending); self.assertEqual(deps.log, [])

    def test_not_written_yet_is_left_to_the_ingest(self):
        deps = FakeDeps([race()], {"600": FIX["provisional"]})
        self.assertEqual(self.follow(deps).run(M(0)), (False, [])); self.assertEqual(deps.log, [])


class StatsTest(Base):
    def test_stats_failure_is_reported_and_does_not_block_the_push(self):
        deps = FakeDeps([race()], {"600": FIX["official"]})
        deps.write_session("600", FIX["official"]["classification"], "FP1")
        deps.stats_fail = True
        pending, problems = self.follow(deps).run(M(6), stats_owed={"2026"})
        self.assertEqual(len(deps.kinds("push")), 1); self.assertIn("stats update 2026 failed", problems[0])
        order = [x[0] for x in deps.log]
        self.assertEqual(order[-1], "push")  # the push of this pass went before the (failed) stats

    def test_failed_stats_and_cache_bump_are_retried(self):
        deps = FakeDeps([race()], {"600": FIX["official"]})
        deps.write_session("600", FIX["provisional"]["classification"], "FP1")
        deps.stats_fail = True
        real_bump = deps.bump_cache; fails = {"n": 1}
        def bump(gp):
            if fails["n"]:
                fails["n"] -= 1; raise RuntimeError("Strapi 502")
            real_bump(gp)
        deps.bump_cache = bump
        f = self.follow(deps)
        pending, problems = f.run(M(8))  # rewrite, then the bump fails: the pass reports it
        self.assertTrue(any("results follow-up failed" in p for p in problems))
        deps.stats_fail = False
        f.run(M(9))
        self.assertEqual(deps.kinds("bump"), [("bump", "63")]); self.assertEqual(deps.kinds("stats"), [("stats", "2026")])

    def test_runner_defers_ingest_stats_to_the_followup(self):
        with mock.patch.object(up, "create_race_result"), mock.patch.object(up, "update_config_for_race_result"), \
             mock.patch.object(up, "process_update_moto_gp_stats") as stats, mock.patch.object(up, "defer_stats", True):
            up.stats_owed.clear()
            up.upload_moto_gp_race_results({"classification": [item(93, 1, "01:39.1")], "records": []},
                                           {93: "g"}, "600", "FP1", {"id": "63"}, "2026")
        stats.assert_not_called(); self.assertEqual(up.stats_owed, {"2026"}); up.stats_owed.clear()

    def test_ingest_waits_while_the_session_is_still_running(self):
        with mock.patch.object(up, "create_race_result") as create, mock.patch.object(up, "update_config_for_race_result"), \
             mock.patch.object(up, "process_update_moto_gp_stats"):
            st = up.upload_moto_gp_race_results({"classification": [item(93, 1, "01:39.1")], "records": [],
                                                 "session": {"status": "CURRENT"}}, {93: "g"}, "601", "PRACTICE", {"id": "63"}, "2026")
        self.assertEqual(st, "no_classification"); create.assert_not_called()


class RunnerTest(Base):
    def test_followup_pending_keeps_the_runner_polling_every_minute(self):
        t = [datetime(2026, 11, 20, 11, 36, tzinfo=timezone.utc)]
        waits = []
        def sleep(s):
            waits.append(s); t[0] += timedelta(seconds=s)
        calls = {"n": 0}
        def followup(now):
            calls["n"] += 1
            return calls["n"] < 4, []
        summary = {"ingested": [], "waiting": [], "skipped_missing_grid": [], "errors": []}
        wr.run(clock=lambda: t[0], sleep=sleep, process=lambda now: summary, max_minutes=30, poll_seconds=60,
               next_start_fn=lambda now: None, followup=followup)
        self.assertEqual(waits[:3], [60.0, 60.0, 60.0])

    def test_followup_crash_is_reported_and_retried(self):
        t = [datetime(2026, 11, 20, 11, 36, tzinfo=timezone.utc)]
        def sleep(s): t[0] += timedelta(seconds=s)
        n = {"c": 0}
        def followup(now):
            n["c"] += 1
            if n["c"] == 1:
                raise RuntimeError("Strapi 502")
            return False, []
        summary = {"ingested": [], "waiting": [], "skipped_missing_grid": [], "errors": []}
        chain, problems = wr.run(clock=lambda: t[0], sleep=sleep, process=lambda now: summary, max_minutes=30,
                                 poll_seconds=60, next_start_fn=lambda now: None, followup=followup)
        self.assertEqual(n["c"], 2); self.assertIn("results follow-up: RuntimeError: Strapi 502", problems)


class IngestPayloadTest(Base):
    """result_fields must keep the first write exactly as before."""

    def ingest(self, cls, rtype):
        with mock.patch.object(up, "create_race_result") as create, mock.patch.object(up, "update_config_for_race_result"), \
             mock.patch.object(up, "process_update_moto_gp_stats"):
            up.upload_moto_gp_race_results({"classification": cls, "records": []}, {c["rider"]["number"]: f"g{c['rider']['number']}" for c in cls},
                                           "600", rtype, {"id": "63"}, "2026")
        return [json.loads(c.kwargs["json_str"]) for c in create.call_args_list]

    def test_practice_q1_and_race_payloads(self):
        self.assertEqual(self.ingest([item(72, 1, "01:39.002")], "FP1")[0],
                         {"race": "600", "seasonGrid": "g72", "position": 1, "points": 0, "laps": 18, "time": "01:39.002", "dnf": False})
        q1 = self.ingest([item(1, 1, "01:38.1"), item(2, 2, "01:38.2"), item(3, 3, "01:38.3")], "QNR1")
        self.assertEqual([c.get("finalPos") for c in q1], [None, None, 13])
        rc = self.ingest([item(72, 1, laps=25, points=25, time="41:02.111"), item(73, None, laps=3, points=0, status="OUTSTND")], "Race")
        self.assertEqual((rc[0]["time"], rc[1]["position"], rc[1]["dnf"], rc[1]["time"]), ("41:02.111", 2, True, ""))


class ReadBackUncachedTest(unittest.TestCase):
    """The Strapi proxy caches identical GraphQL queries: every row count and row read must be a fresh request."""

    def test_row_reads_are_never_a_cache_hit(self):
        from cron.strapi_api import apis
        resp = mock.Mock(); resp.json.return_value = {"data": {"raceResults": {"data": []}}}
        with mock.patch.object(apis, "get_graphql_endpoint", return_value="https://x/graphql"), \
             mock.patch.object(apis, "get_headers", return_value={}), \
             mock.patch.object(apis.requests, "post", return_value=resp) as post:
            apis.get_race_results_for_race_event(is_f1_feed=False, race_id="600")
            apis.get_race_results_for_race_event(is_f1_feed=False, race_id="600")
            apis.get_session_rows(False, "600")
            apis.get_session_rows(False, "600")
        qs = [c.kwargs["json"]["query"] for c in post.call_args_list]
        self.assertEqual(len(set(qs)), 4)
        self.assertTrue(all(q.startswith("# ") for q in qs))

    def test_session_rows_error_is_raised_not_read_as_empty(self):
        from cron.strapi_api import apis
        resp = mock.Mock(); resp.json.return_value = {"errors": [{"message": "boom"}], "data": None}
        with mock.patch.object(apis, "get_graphql_endpoint", return_value="https://x/graphql"), \
             mock.patch.object(apis, "get_headers", return_value={}), mock.patch.object(apis.requests, "post", return_value=resp):
            with self.assertRaises(RuntimeError):
                apis.get_session_rows(False, "600")


if __name__ == "__main__":
    unittest.main()


class FinalReviewTest(unittest.TestCase):
    def setUp(self):
        logger.remove()

    def test_corrections_never_round_an_official_time_back_down(self):
        from cron.data_upload.moto_gp import corrections
        rows = [{"id": "1", "number": 72, "position": 1, "points": 0, "laps": 18, "time": "01:39.002", "dnf": False}]
        stale = [{"position": 1, "rider": {"number": 72}, "best_lap": {"time": "1:39.00"}, "total_laps": 18}]
        changes, held = corrections.plan_session("FP1", stale, rows, [])
        self.assertEqual(changes, []); self.assertIn("coarser", held[0])
        finer = [{"position": 1, "rider": {"number": 72}, "best_lap": {"time": "01:39.002"}, "total_laps": 18}]
        rows[0]["time"] = "1:39.00"
        changes, held = corrections.plan_session("FP1", finer, rows, [])
        self.assertEqual([c[2] for c in changes], ["01:39.002"]); self.assertEqual(held, [])

    def test_ingest_cache_bump_failure_keeps_stats_and_the_bump_owed(self):
        with mock.patch.object(up, "create_race_result"), \
             mock.patch.object(up, "update_config_for_race_result", side_effect=RuntimeError("Strapi 502")), \
             mock.patch.object(up, "defer_stats", True):
            up.stats_owed.clear(); up.bump_owed.clear()
            with self.assertRaises(RuntimeError):
                up.upload_moto_gp_race_results({"classification": [item(93, 1, "01:39.1")], "records": []},
                                               {93: "g"}, "600", "FP1", {"id": "63"}, "2026")
        self.assertEqual((up.stats_owed, up.bump_owed), ({"2026"}, {"63"}))
        up.stats_owed.clear(); up.bump_owed.clear()

    def test_f1_cache_bump_keeps_its_old_non_raising_behaviour(self):
        from cron.strapi_api import apis
        resp = mock.Mock(); resp.json.return_value = {"errors": [{"message": "x"}]}
        cfg = mock.Mock(return_value={"raceResultFastestLapForGrandPrixJson": {}})
        with mock.patch.object(apis, "get_config", cfg), mock.patch.object(apis, "get_graphql_endpoint", return_value="u"), \
             mock.patch.object(apis, "get_headers", return_value={}), mock.patch.object(apis.requests, "post", return_value=resp):
            apis.update_config_for_race_result(is_f1_feed=True, gp_id="5")  # no raise
            with self.assertRaises(RuntimeError):
                apis.update_config_for_race_result(is_f1_feed=False, gp_id="63", strict=True)

    def test_session_lookup_miss_is_not_cached(self):
        deps = FakeDeps([race()], {"600": FIX["official"]}); deps.write_session("600", FIX["official"]["classification"], "FP1")
        answers = iter([None, "uuid-600"])
        deps.session_uuid = lambda r: next(answers)
        f = rf.Followup(deps, FakeStore(), True)
        pending, problems = f.run(M(6)); self.assertIn("session not found", problems[0])
        f.run(M(7)); self.assertEqual(len(deps.kinds("push")), 1)
