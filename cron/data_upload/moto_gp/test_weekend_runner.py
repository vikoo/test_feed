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
        self.assertEqual(passes[1], fp1)  # slept straight to the session start, no busy polling
        self.assertTrue(all(b - a <= timedelta(seconds=120) for a, b in zip(passes[1:], passes[2:])))
        self.assertLess(c.t, fp1 + timedelta(minutes=55))  # results picked up within one poll

    def test_chains_when_next_session_is_after_the_job_limit(self):
        c = FakeClock(T0)
        sat = T0 + timedelta(hours=20)
        chain, _ = wr.run(clock=c, sleep=c.sleep, process=lambda now: summary(), next_start_fn=lambda now: sat, max_minutes=330)
        self.assertTrue(chain); self.assertEqual(c.t, T0 + timedelta(minutes=330))

    def test_chains_while_a_session_is_still_waiting_at_the_limit(self):
        c = FakeClock(T0)
        chain, _ = wr.run(clock=c, sleep=c.sleep, process=lambda now: summary(waiting=["POR Race"]), next_start_fn=lambda now: None, max_minutes=60)
        self.assertTrue(chain)

    def test_polling_does_not_overshoot_the_next_event(self):
        poll = timedelta(seconds=120)
        self.assertEqual(wr.next_wake(T0, True, T0 + timedelta(seconds=60), T0 + timedelta(hours=1), poll), T0 + timedelta(seconds=60))
        self.assertEqual(wr.next_wake(T0, True, T0 + timedelta(hours=2), T0 + timedelta(hours=3), poll), T0 + poll)

    def test_never_chains_a_run_that_ended_quickly(self):
        self.assertFalse(wr.should_chain(True, T0, T0 + timedelta(minutes=5), T0))
        self.assertTrue(wr.should_chain(True, None, T0 + timedelta(minutes=30), T0))
        self.assertFalse(wr.should_chain(False, T0 + timedelta(hours=40), T0 + timedelta(minutes=30), T0))

    def test_api_outage_keeps_retrying_and_reports(self):
        c = FakeClock(T0)
        def process(now): raise ConnectionError("strapi down")
        chain, problems = wr.run(clock=c, sleep=c.sleep, process=process, next_start_fn=lambda now: None, max_minutes=30)
        self.assertTrue(chain); self.assertTrue(problems)
        self.assertEqual(c.t, T0 + timedelta(minutes=30))


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
            self.assertEqual(up.upload_moto_gp_race_results(cls, {93: "1", 89: "2"}, "600", "Race", {"id": "47"}, "2026", race_start=old), "ingested")
            self.assertEqual(create.call_count, 2)
