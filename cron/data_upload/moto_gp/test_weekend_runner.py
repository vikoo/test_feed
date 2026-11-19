import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from loguru import logger

from cron.data_upload.moto_gp import moto_gp_data_upload as up
from cron.data_upload.moto_gp import weekend_runner as wr
from cron.strapi_api.apis import build_season_grid_map

T0 = datetime(2026, 11, 20, 8, 0, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self, t): self.t = t
    def __call__(self): return self.t
    def sleep(self, seconds): self.t += timedelta(seconds=seconds)


def summary(waiting=(), ingested=(), skipped=(), errors=()):
    return {"waiting": list(waiting), "ingested": list(ingested), "skipped_missing_grid": list(skipped), "errors": list(errors)}


class RunnerTest(unittest.TestCase):
    def setUp(self):
        logger.remove()

    def test_off_weekend_exits_at_once_without_chain(self):
        c = FakeClock(T0)
        chain, problems = wr.run(clock=c, sleep=c.sleep, process=lambda now: summary(), next_start_fn=lambda now: None)
        self.assertFalse(chain); self.assertEqual(problems, []); self.assertEqual(c.t, T0)

    def test_polls_until_classification_then_finishes_weekend(self):
        c = FakeClock(T0)
        fp1 = T0 + timedelta(minutes=30)
        passes = []
        def process(now):
            passes.append(now)
            if now < fp1 + timedelta(minutes=50): return summary(waiting=["POR FP1"] if now >= fp1 else [])
            return summary(ingested=["POR FP1"] if len(passes) < 99 else [])
        nxt = lambda now: fp1 if now < fp1 else None
        chain, problems = wr.run(clock=c, sleep=c.sleep, process=process, next_start_fn=nxt, poll_seconds=120)
        self.assertFalse(chain)
        self.assertIn(fp1, passes)  # awake exactly at the session start
        before = [p for p in passes if p <= fp1]
        self.assertTrue(all(b - a <= wr.MAX_IDLE for a, b in zip(before, before[1:])))  # timetable re-checked every 10 min
        self.assertLessEqual(len(before), 5)  # no busy polling while idle
        after = [p for p in passes if p >= fp1]
        self.assertTrue(all(b - a <= timedelta(seconds=120) for a, b in zip(after, after[1:])))
        self.assertLess(c.t, fp1 + timedelta(minutes=55))  # results picked up within one poll

    def test_chains_when_next_session_is_after_the_job_limit(self):
        c = FakeClock(T0)
        sat = T0 + timedelta(hours=20)
        chain, _ = wr.run(clock=c, sleep=c.sleep, process=lambda now: summary(), next_start_fn=lambda now: sat, max_minutes=330)
        self.assertTrue(chain)
        self.assertLessEqual(c.t, T0 + timedelta(minutes=330) - wr.HANDOVER_MARGIN)  # hands over before the limit
        self.assertGreaterEqual(c.t, T0 + timedelta(minutes=330) - wr.HANDOVER_WINDOW)

    def test_chains_while_a_session_is_still_waiting_at_the_limit(self):
        c = FakeClock(T0)
        chain, _ = wr.run(clock=c, sleep=c.sleep, process=lambda now: summary(waiting=["POR Race"]), next_start_fn=lambda now: None, max_minutes=60)
        self.assertTrue(chain)

    def test_polling_does_not_overshoot_the_next_event(self):
        poll = timedelta(seconds=120)
        self.assertEqual(wr.next_wake(T0, True, T0 + timedelta(seconds=60), T0 + timedelta(hours=1), poll), T0 + timedelta(seconds=60))
        self.assertEqual(wr.next_wake(T0, True, T0 + timedelta(hours=2), T0 + timedelta(hours=3), poll), T0 + poll)
        # a reminder that fell during the pass just finished: next pass at once, not one poll later
        self.assertEqual(wr.next_wake(T0, False, T0 - timedelta(seconds=5), T0 + timedelta(hours=3), poll), T0)
        self.assertEqual(wr.next_wake(T0, True, T0 - timedelta(seconds=5), T0 + timedelta(hours=3), poll), T0)

    def test_never_chains_a_run_that_ended_quickly(self):
        self.assertFalse(wr.should_chain(True, T0, T0 + timedelta(minutes=5), T0))
        self.assertTrue(wr.should_chain(True, None, T0 + timedelta(minutes=30), T0))
        self.assertFalse(wr.should_chain(False, T0 + timedelta(hours=40), T0 + timedelta(minutes=30), T0))

    def test_api_outage_keeps_retrying_and_reports(self):
        c = FakeClock(T0)
        def process(now): raise ConnectionError("strapi down")
        chain, problems = wr.run(clock=c, sleep=c.sleep, process=process, next_start_fn=lambda now: None, max_minutes=30)
        self.assertTrue(chain); self.assertTrue(problems)
        self.assertLessEqual(c.t, T0 + timedelta(minutes=30))
        self.assertGreaterEqual(c.t, T0 + timedelta(minutes=wr.MIN_MINUTES_BEFORE_CHAIN))


def race(rid, rtype, start, short="POR"):
    return {"id": str(rid), "attributes": {"type": rtype, "startTime": start,
            "grandPrix": {"data": {"id": "47", "attributes": {"shortName": short, "season": {"data": {"attributes": {"year": "2026"}}}}}}}}


class UploaderTest(unittest.TestCase):
    def setUp(self):
        logger.remove()

    def test_grid_map_falls_back_to_old_grid_only_when_needed(self):
        grids = [{"id": "96", "attributes": {"driverNumber": 41, "isOldGrid": True}},
                 {"id": "79", "attributes": {"driverNumber": 36, "isOldGrid": None}},
                 {"id": "50", "attributes": {"driverNumber": 36, "isOldGrid": True}},
                 {"id": "94", "attributes": {"driverNumber": 30, "isOldGrid": True}},
                 {"id": "97", "attributes": {"driverNumber": 30, "isOldGrid": True}}]
        self.assertEqual(build_season_grid_map(grids), {36: "79"})
        self.assertEqual(build_season_grid_map(grids, fill_from_old_grids=True), {36: "79", 41: "96", 30: "97"})

    def test_missing_grid_writes_nothing(self):
        res = {"classification": [{"position": 1, "rider": {"number": 93, "id": "a"}, "points": 25},
                                  {"position": 2, "rider": {"number": 99, "id": "b"}, "points": 20}], "records": []}
        with mock.patch.object(up, "create_race_result") as create:
            with self.assertRaises(up.MissingSeasonGridError) as e:
                up.upload_moto_gp_race_results(res, {93: "61"}, "600", "Race", {"id": "47"}, "2026")
        create.assert_not_called(); self.assertEqual(e.exception.numbers, [99])

    def test_process_reports_per_session_and_continues(self):
        now = datetime(2026, 11, 22, 15, 0, tzinfo=timezone.utc)
        races = [race(607, "Race", "2026-11-22T14:00:00.000Z"),     # 60 min old, no classification yet
                 race(606, "Sprint", "2026-11-22T14:50:00.000Z"),   # 10 min old: cannot be final
                 race(605, "QNR2", "2026-11-21T10:00:00.000Z"),     # grid missing
                 race(604, "FP2", "2026-11-21T09:00:00.000Z")]      # already in Strapi
        counts = {"607": 0, "606": 0, "605": 0, "604": 22}
        def fetch(data):
            rid = data["data"]["races"]["data"][0]["id"]
            cl = [] if rid == "607" else [{"position": 1, "rider": {"number": 99, "id": "x"}}]
            return {"classification": cl, "records": []}, {93: "61"}, "2026"
        with mock.patch.object(up, "get_latest_past_race", return_value={"data": {"races": {"data": races}}}), \
             mock.patch.object(up, "get_race_results_for_race_event", side_effect=lambda is_f1_feed, race_id: {"data": {"raceResults": {"data": [0] * counts[race_id]}}}), \
             mock.patch.object(up, "fetch_and_upload_race_data", side_effect=fetch), \
             mock.patch.object(up, "create_race_result") as create:
            s = up.process(now=now)
        create.assert_not_called()
        self.assertEqual(len(s["waiting"]), 2)
        self.assertEqual(len(s["skipped_missing_grid"]), 1)
        self.assertEqual(s["errors"], []); self.assertEqual(s["ingested"], [])


if __name__ == "__main__":
    unittest.main()


class HardeningTest(unittest.TestCase):
    def setUp(self):
        logger.remove()

    def test_long_outage_stops_handing_over(self):
        c = FakeClock(T0)
        def process(now): raise ConnectionError("token revoked")
        chain, problems = wr.run(clock=c, sleep=c.sleep, process=process, next_start_fn=lambda now: None, max_minutes=600)
        self.assertFalse(chain)
        self.assertLess(c.t - T0, timedelta(hours=wr.MAX_HOURS_WITHOUT_SUCCESS, minutes=5))

    def test_red_flag_part_one_with_zero_points_is_not_ingested(self):
        cls = {"classification": [{"position": 1, "rider": {"number": 93, "id": "a"}, "points": 0},
                                  {"position": 2, "rider": {"number": 89, "id": "b"}, "points": None}], "records": []}
        recent = (datetime.now(timezone.utc) - timedelta(minutes=50)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        old = (datetime.now(timezone.utc) - timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        with mock.patch.object(up, "create_race_result") as create, \
             mock.patch.object(up, "update_config_for_race_result"), mock.patch.object(up, "process_update_moto_gp_stats"), \
             mock.patch.object(up, "send_race_complete_notification"), mock.patch.object(up.time, "sleep"):
            self.assertEqual(up.upload_moto_gp_race_results(cls, {93: "1", 89: "2"}, "600", "Race", {"id": "47"}, "2026", race_start=recent), "no_classification")
            create.assert_not_called()
            self.assertEqual(up.upload_moto_gp_race_results(cls, {93: "1", 89: "2"}, "600", "Race", {"id": "47"}, "2026", race_start=old), "no_classification")
            create.assert_not_called()  # never written with missing points, however long it takes

    def test_order_published_before_points_waits(self):
        pts = [25, 20, 16, 13, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]
        full = [{"position": i + 1, "rider": {"number": i + 1, "id": str(i)}, "points": p} for i, p in enumerate(pts)] + \
               [{"position": 16, "rider": {"number": 16, "id": "16"}, "points": 0},
                {"position": None, "rider": {"number": 17, "id": "17"}, "points": 0}]  # out of the points, DNF
        self.assertEqual(up.points_missing(full, "Race"), [])
        partial = [dict(c) for c in full]; partial[3]["points"] = None; partial[14]["points"] = 0
        self.assertEqual(up.points_missing(partial, "Race"), [4, 15])
        self.assertEqual(up.points_missing(full[:5] + [{"position": None, "rider": {"number": 9}, "points": 0}], "Race"), [])  # 5 finishers
        sprint = [{"position": i + 1, "rider": {"number": i + 1}, "points": p} for i, p in enumerate([12, 9, 7, 6, 5, 4, 3, 2, 1, 0])]
        self.assertEqual(up.points_missing(sprint, "Sprint"), [])
        half = [{"position": i + 1, "rider": {"number": i + 1}, "points": p} for i, p in enumerate([12.5, 10, 8, 6.5, 5.5, 5, 4.5, 4, 3.5, 3, 2.5, 2, 1.5, 1, 0.5])]
        self.assertEqual(up.points_missing(half, "Race"), [])
        self.assertEqual(up.points_missing(partial, "QNR2"), [])

    def test_points_in_means_written_at_once(self):
        cls = {"classification": [{"position": 1, "rider": {"number": 93, "id": "a"}, "points": 25},
                                  {"position": 2, "rider": {"number": 89, "id": "b"}, "points": 20}], "records": []}
        recent = (datetime.now(timezone.utc) - timedelta(minutes=45)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        with mock.patch.object(up, "create_race_result") as create, \
             mock.patch.object(up, "update_config_for_race_result"), mock.patch.object(up, "process_update_moto_gp_stats"), \
             mock.patch.object(up, "send_race_complete_notification") as push, mock.patch.object(up.time, "sleep"), \
             mock.patch.object(up, "results_readable", return_value=(True, "")):
            self.assertEqual(up.upload_moto_gp_race_results(cls, {93: "1", 89: "2"}, "600", "Race", {"id": "47"}, "2026", race_start=recent), "ingested")
        self.assertEqual(create.call_count, 2); push.assert_called_once()


class ResultsPushTest(unittest.TestCase):
    """Purple Sector rules: announce only fresh sessions, and only once the app can read the results."""
    def setUp(self):
        logger.remove()

    CLS = {"classification": [{"position": 1, "rider": {"number": 93, "id": "a"}, "points": 25}], "records": []}

    def _upload(self, hours_ago, readable=(True, "")):
        start = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        with mock.patch.object(up, "create_race_result"), mock.patch.object(up, "update_config_for_race_result"), \
             mock.patch.object(up, "process_update_moto_gp_stats"), mock.patch.object(up.time, "sleep"), \
             mock.patch.object(up, "send_race_complete_notification") as push, \
             mock.patch.object(up, "results_readable", return_value=readable):
            status = up.upload_moto_gp_race_results(self.CLS, {93: "1"}, "600", "Race", {"id": "47"}, "2026", race_start=start)
        return status, push.call_count

    def test_fresh_session_is_announced(self):
        self.assertEqual(self._upload(1), ("ingested", 1))

    def test_session_written_a_day_later_is_not_announced(self):
        self.assertEqual(self._upload(30), ("ingested", 0))

    def test_push_held_when_the_app_cannot_read_the_results_yet(self):
        status, pushes = self._upload(1, readable=(False, "Strapi returns 0 of 1 rows"))
        self.assertEqual(pushes, 0); self.assertTrue(status.startswith("ingested_push_held:"))

    def test_held_push_is_reported_and_the_session_counts_as_written(self):
        r = [race(607, "Race", "2026-11-22T13:00:00.000Z")]
        with mock.patch.object(up, "get_latest_past_race", return_value={"data": {"races": {"data": r}}}), \
             mock.patch.object(up, "_process_session", return_value="ingested_push_held:Strapi returns 0 of 22 rows"):
            s = up.process(now=up.parse_time("2026-11-22T14:00:00.000Z"))
        self.assertEqual(len(s["ingested"]), 1); self.assertIn("push held", s["errors"][0])

    def test_read_back_retries_then_passes(self):
        answers = iter([{"data": {"raceResults": {"data": []}}}, {"data": {"raceResults": {"data": [1, 2]}}}])
        with mock.patch.object(up, "get_race_results_for_race_event", side_effect=lambda **kw: next(answers)), \
             mock.patch.object(up, "get_config", return_value={"raceResultFastestLapForGrandPrixJson": {"47": "1"}}), \
             mock.patch.object(up.time, "sleep"):
            self.assertEqual(up.results_readable("600", 2, "47"), (True, ""))


class MovedSessionTest(unittest.TestCase):
    """Reviewer case: Race moved one hour earlier while the runner is idle. The reminder must still go."""
    def setUp(self):
        logger.remove()

    def test_session_moved_earlier_while_idle_still_reminded(self):
        c = FakeClock(datetime(2026, 11, 22, 10, 30, tzinfo=timezone.utc))
        old, new = datetime(2026, 11, 22, 13, 0, tzinfo=timezone.utc), datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
        moved_at = datetime(2026, 11, 22, 10, 31, tzinfo=timezone.utc)
        start = lambda now: new if now >= moved_at else old
        sent = []
        def remind(now):
            if timedelta(0) < start(now) - now <= timedelta(minutes=15) and not sent:
                sent.append(now)
            return []
        nxt = lambda now: min(e for e in (start(now) - timedelta(minutes=15), start(now)) if e > now) if now < start(now) else None
        wr.run(clock=c, sleep=c.sleep, process=lambda now: summary(), next_start_fn=nxt, remind=remind, max_minutes=330)
        self.assertEqual(len(sent), 1)
        self.assertLessEqual(sent[0], new - timedelta(minutes=5))


class GiveUpReportTest(unittest.TestCase):
    def setUp(self):
        logger.remove()

    def test_session_without_classification_is_reported_once_when_waiting_ends(self):
        r = [race(607, "Race", "2026-11-22T13:00:00.000Z")]
        out = []
        for hours in (7.9, 8.1, 9.0, 11.0):
            now = up.parse_time("2026-11-22T13:00:00.000Z") + timedelta(hours=hours)
            with mock.patch.object(up, "get_latest_past_race", return_value={"data": {"races": {"data": r}}}), \
                 mock.patch.object(up, "_process_session", return_value="no_classification"):
                s = up.process(now=now)
            out.append((len(s["waiting"]), len(s["errors"])))
        self.assertEqual(out, [(1, 0), (0, 1), (0, 1), (0, 0)])


class QuietHandoverTest(unittest.TestCase):
    """Reviewer case: the next run can take 20+ minutes to start. A handover must never sit just before a reminder."""
    def setUp(self):
        logger.remove()

    def test_no_reminder_lost_with_a_slow_handover_at_any_start_offset(self):
        fp1 = datetime(2026, 11, 20, 10, 45, tzinfo=timezone.utc)
        starts = [fp1, fp1 + timedelta(minutes=255), fp1 + timedelta(hours=23, minutes=25), fp1 + timedelta(hours=24, minutes=5),
                  fp1 + timedelta(hours=28, minutes=15), fp1 + timedelta(hours=50, minutes=15)]
        rems = [s - timedelta(minutes=15) for s in starts]
        for handover in (4, 20, 40):
            for offset_min in range(0, 26 * 60, 25):
                c = FakeClock(fp1 - timedelta(minutes=offset_min) - timedelta(minutes=20))
                sent = []
                def remind(now):
                    for s in starts:
                        if timedelta(0) < s - now <= timedelta(minutes=15) and s not in sent:
                            sent.append(s)
                    return []
                nxt = lambda now: min([e for e in starts + rems if e > now], default=None)
                nrem = lambda now: min([e for e in rems if e > now], default=None)
                for _ in range(40):
                    chain, _p = wr.run(clock=c, sleep=c.sleep, process=lambda now: summary(), next_start_fn=nxt,
                                       remind=remind, next_reminder_fn=nrem, max_minutes=330)
                    if not chain:
                        break
                    c.t += timedelta(minutes=handover)
                self.assertEqual(len(sent), 6, (handover, offset_min))
