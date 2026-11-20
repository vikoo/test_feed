"""A session written from a provisional classification is rewritten as soon as motogp.com marks it official.

Portugal FP1 2026: written 11:36 UTC from the provisional feed ("1:39.00"), official ("01:39.002") about
11:43 UTC, and the app kept the rounded times until the 15-minute corrections check.
"""
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from loguru import logger

from cron.data_upload.moto_gp import moto_gp_data_upload as up
from cron.data_upload.moto_gp import weekend_runner as wr

NOW = datetime(2026, 11, 20, 11, 36, tzinfo=timezone.utc)


def item(num, pos, lap, laps=18, points=None, time=None, status="INSTND"):
    c = {"position": pos, "rider": {"number": num, "id": f"r{num}"}, "best_lap": {"number": 9, "time": lap},
         "total_laps": laps, "status": status}
    if points is not None:
        c["points"] = points
    if time is not None:
        c["time"] = time
    return c


# Portugal FP1 2026, top 3: provisional feed at 11:37 UTC and official feed at 11:43 UTC.
FP1_PROV = [item(72, 1, "1:39.00"), item(89, 2, "1:39.14", 19), item(73, 3, "1:39.24", 15)]
FP1_OFF = [item(72, 1, "01:39.002"), item(89, 2, "01:39.144", 19), item(73, 3, "01:39.245", 15)]
GRID = {72: "g72", 89: "g89", 73: "g73"}
ROWS = {72: "r1", 89: "r2", 73: "r3"}


def feed(cls, official, session="s-fp1"):
    return {"classification": cls, "records": [], "official": official, "session": {"id": session}}


def strapi_rows(rows=ROWS):
    return {"data": {"raceResults": {"data": [{"id": rid, "attributes": {"seasonGrid": {"data": {"attributes": {"driverNumber": n}}}}}
                                              for n, rid in rows.items()]}}}


class Base(unittest.TestCase):
    def setUp(self):
        logger.remove()
        up._provisional.clear()
        self.addCleanup(up._provisional.clear)

    def ingest(self, cls, official, race_type="FP1", race_id="600", grid=GRID):
        start = (datetime.now(timezone.utc) - timedelta(minutes=50)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        with mock.patch.object(up, "create_race_result") as create, mock.patch.object(up, "update_config_for_race_result"), \
             mock.patch.object(up, "process_update_moto_gp_stats"), mock.patch.object(up.time, "sleep"), \
             mock.patch.object(up, "send_results_push") as push, mock.patch.object(up, "results_readable", return_value=(True, "")):
            status = up.upload_moto_gp_race_results(feed(cls, official), grid, race_id, race_type, {"id": "63"}, "2026", race_start=start)
        return status, [json.loads(c.kwargs["json_str"]) for c in create.call_args_list], push.call_count

    def refresh(self, official_feed, race_id="600", now=None, rows=ROWS):
        with mock.patch.object(up, "fetch_race_results", return_value=official_feed) as fetch, \
             mock.patch.object(up, "update_race_result") as update, \
             mock.patch.object(up, "update_config_for_race_result") as cache, \
             mock.patch.object(up, "process_update_moto_gp_stats") as stats, \
             mock.patch.object(up, "send_results_push") as push:
            status = up.refresh_provisional(race_id, strapi_rows(rows), now=now or datetime.now(timezone.utc))
        writes = [(c.kwargs["row_id"], json.loads(c.kwargs["json_str"])) for c in update.call_args_list]
        return status, writes, fetch.call_count, cache.call_count, stats.call_count, push.call_count


class IngestPayloadTest(Base):
    """The refactor into result_fields must not change what the first write sends."""

    def test_practice_payload_unchanged(self):
        _, created, pushes = self.ingest(FP1_OFF, official=True)
        self.assertEqual(created[0], {"race": "600", "seasonGrid": "g72", "position": 1, "points": 0, "laps": 18,
                                      "time": "01:39.002", "dnf": False})
        self.assertEqual(pushes, 1)

    def test_qnr1_final_pos_and_race_fields_unchanged(self):
        q1 = [item(72, 1, "01:38.1"), item(89, 2, "01:38.2"), item(73, 3, "01:38.3")]
        _, created, _ = self.ingest(q1, official=True, race_type="QNR1")
        self.assertEqual([c.get("finalPos") for c in created], [None, None, 13])
        race = [item(72, 1, "", 25, points=25, time="41:02.111"), item(89, 2, "", 25, points=20, time="+1.2"),
                item(73, None, "", 3, points=0, status="OUTSTND")]
        _, created, _ = self.ingest(race, official=True, race_type="Race")
        self.assertEqual(created[0]["time"], "41:02.111")
        self.assertEqual((created[2]["position"], created[2]["dnf"], created[2]["time"]), (3, True, ""))


class WatchTest(Base):
    def test_provisional_ingest_is_watched_official_is_not(self):
        self.ingest(FP1_OFF, official=True)
        self.assertNotIn("600", up._provisional)
        status, _, pushes = self.ingest(FP1_PROV, official=False)
        self.assertEqual((status, pushes), ("ingested", 1))  # written and announced at once, as before
        self.assertEqual(up._provisional["600"]["session"], "s-fp1")
        self.assertEqual(up._provisional["600"]["fields"][72]["time"], "1:39.00")

    def test_process_keeps_the_runner_polling_while_provisional(self):
        """Waiting -> the runner polls every 2 minutes instead of idling 10."""
        up._provisional["600"] = {"at": NOW, "session": "s", "race_type": "FP1", "gp_id": "63", "year": "2026", "fields": {}}
        races = [{"id": "600", "attributes": {"type": "FP1", "startTime": "2026-11-20T10:45:00.000Z",
                  "grandPrix": {"data": {"id": "63", "attributes": {"shortName": "POR", "season": {"data": {"attributes": {"year": "2026"}}}}}}}}]
        with mock.patch.object(up, "get_latest_past_race", return_value={"data": {"races": {"data": races}}}), \
             mock.patch.object(up, "_process_session", return_value="provisional"):
            s = up.process(now=NOW + timedelta(minutes=2))
        self.assertEqual(len(s["waiting"]), 1); self.assertEqual(s["errors"], [])
        wake = wr.next_wake(NOW, bool(s["waiting"]), NOW + timedelta(hours=3), NOW + timedelta(hours=5), timedelta(minutes=2))
        self.assertEqual(wake, NOW + timedelta(minutes=2))

    def test_session_with_rows_and_no_watch_makes_no_api_call(self):
        with mock.patch.object(up, "get_race_results_for_race_event", return_value=strapi_rows()), \
             mock.patch.object(up, "fetch_race_results") as fetch, mock.patch.object(up, "fetch_and_upload_race_data") as fau:
            self.assertEqual(up._process_session({"attributes": {"startTime": "x"}}, "604", "FP2", {"id": "63"}), "exists")
        fetch.assert_not_called(); fau.assert_not_called()


class RefreshTest(Base):
    def watch(self, cls=FP1_PROV, race_type="FP1"):
        self.ingest(cls, official=False, race_type=race_type)

    def test_still_provisional_writes_nothing(self):
        self.watch()
        status, writes, fetches, cache, stats, pushes = self.refresh(feed(FP1_PROV, False))
        self.assertEqual((status, writes, cache, pushes), ("provisional", [], 0, 0))
        self.assertIn("600", up._provisional)

    def test_portugal_fp1_official_times_rewritten(self):
        self.watch()
        status, writes, _, cache, stats, pushes = self.refresh(feed(FP1_OFF, True))
        self.assertEqual(status, "refreshed")
        self.assertEqual(writes, [("r1", {"time": "01:39.002"}), ("r2", {"time": "01:39.144"}), ("r3", {"time": "01:39.245"})])
        self.assertEqual((cache, stats, pushes), (1, 0, 0))  # app cache bumped, order unchanged: no stats, never a second push
        self.assertNotIn("600", up._provisional)

    def test_official_identical_to_provisional_writes_nothing(self):
        self.watch(FP1_OFF)
        status, writes, _, cache, _, _ = self.refresh(feed(FP1_OFF, True))
        self.assertEqual((status, writes, cache), ("refreshed", [], 0))

    def test_cancelled_lap_changes_practice_order_and_stats(self):
        self.watch()
        off = [item(89, 1, "01:39.144", 19), item(72, 2, "01:39.201"), item(73, 3, "01:39.245", 15)]
        status, writes, _, cache, stats, _ = self.refresh(feed(off, True))
        self.assertEqual(writes[0], ("r2", {"position": 1, "time": "01:39.144"}))
        self.assertEqual(writes[1], ("r1", {"position": 2, "time": "01:39.201"}))
        self.assertEqual((cache, stats), (1, 1))

    def test_qnr1_final_pos_follows_the_official_order(self):
        q1 = [item(72, 1, "1:38.10"), item(89, 2, "1:38.20"), item(73, 3, "1:38.30")]
        self.watch(q1, race_type="QNR1")
        off = [item(72, 1, "01:38.101"), item(73, 2, "01:38.199"), item(89, 3, "01:38.201")]
        _, writes, _, _, stats, _ = self.refresh(feed(off, True))
        w = dict(writes)
        self.assertEqual(w["r3"], {"position": 2, "time": "01:38.199", "finalPos": None})
        self.assertEqual(w["r2"], {"position": 3, "time": "01:38.201", "finalPos": 13})
        self.assertEqual(stats, 1)

    def test_race_only_time_and_laps_order_stays_with_the_pdf_check(self):
        prov = [item(72, 1, "", 25, points=25, time="41:02.11"), item(89, 2, "", 25, points=20, time="+1.20")]
        self.ingest(prov, official=False, race_type="Race", grid={72: "g72", 89: "g89"})
        off = [item(89, 1, "", 25, points=25, time="41:02.115"), item(72, 2, "", 25, points=20, time="+1.203")]
        status, writes, _, _, stats, _ = self.refresh(feed(off, True), rows={72: "r1", 89: "r2"})
        self.assertEqual(sorted(writes), [("r1", {"time": "+1.203"}), ("r2", {"time": "41:02.115"})])
        self.assertEqual(stats, 0)

    def test_rider_set_changed_is_left_to_corrections(self):
        self.watch()
        status, writes, _, cache, _, _ = self.refresh(feed(FP1_OFF[:2], True))
        self.assertEqual((status, writes, cache), ("exists", [], 0))
        self.assertNotIn("600", up._provisional)

    def test_gives_up_after_the_watch_window(self):
        self.watch()
        late = up._provisional["600"]["at"] + timedelta(minutes=up.PROVISIONAL_WATCH_MINUTES + 1)
        status, writes, fetches, _, _, _ = self.refresh(feed(FP1_OFF, True), now=late)
        self.assertEqual((status, writes, fetches), ("exists", [], 0))
        self.assertNotIn("600", up._provisional)

    def test_write_failure_keeps_the_watch_for_the_next_pass(self):
        self.watch()
        with mock.patch.object(up, "fetch_race_results", return_value=feed(FP1_OFF, True)), \
             mock.patch.object(up, "update_race_result", side_effect=RuntimeError("Strapi 502")), \
             mock.patch.object(up, "update_config_for_race_result"):
            with self.assertRaises(RuntimeError):
                up.refresh_provisional("600", strapi_rows())
        self.assertIn("600", up._provisional)  # process() reports the error and keeps polling
        status, writes, _, _, _, _ = self.refresh(feed(FP1_OFF, True))
        self.assertEqual((status, len(writes)), ("refreshed", 3))


if __name__ == "__main__":
    unittest.main()


class ReadBackUncachedTest(unittest.TestCase):
    """Portugal FP1 2026: the Strapi proxy served the 0-row answer from before the write to the read-back
    ("results push held: Strapi returns 0 of 22 rows"). Every row count must be a fresh request."""

    def test_row_count_query_is_never_a_cache_hit(self):
        from cron.strapi_api import apis
        resp = mock.Mock(); resp.json.return_value = {"data": {"raceResults": {"data": []}}}
        with mock.patch.object(apis, "get_graphql_endpoint", return_value="https://x/graphql"), \
             mock.patch.object(apis, "get_headers", return_value={}), \
             mock.patch.object(apis.requests, "post", return_value=resp) as post:
            apis.get_race_results_for_race_event(is_f1_feed=False, race_id="600")
            apis.get_race_results_for_race_event(is_f1_feed=False, race_id="600")
        q1, q2 = (c.kwargs["json"]["query"] for c in post.call_args_list)
        self.assertNotEqual(q1, q2)
        self.assertTrue(q1.startswith("# ") and "raceResults" in q1)
        self.assertEqual(post.call_args_list[0].kwargs["json"]["variables"], {"raceId": "600"})
