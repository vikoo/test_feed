import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from loguru import logger

from cron.data_upload.moto_gp import post_race as pr

NOW = datetime(2026, 11, 22, 16, 0, tzinfo=timezone.utc)


def q(row, typ, num, pos, final=None, sprint=None):
    return {"id": row, "type": typ, "number": num, "position": pos, "finalPos": final, "sprintFinalPos": sprint}


class PostRaceTest(unittest.TestCase):
    def setUp(self):
        logger.remove()

    def test_parse_grid_both_pdf_layouts(self):
        self.assertEqual(pr.parse_grid_text("89JorgeMARTIN\n1'42.371\n21 laps\n93MarcMARQUEZ\n"), [89, 93])
        self.assertEqual(pr.parse_grid_text("89 Jorge MARTIN\n93 Marc MARQUEZ\n"), [89, 93])

    def test_parse_fastest_lap(self):
        line = "Fastest Lap: Lap 4   Jorge MARTIN      1'29.752   171.2 Km/h"
        self.assertEqual(pr.parse_fastest_lap(line), (4, "Jorge MARTIN", "1'29.752"))
        self.assertIsNone(pr.parse_fastest_lap("no fastest lap here"))

    def test_red_flag_takes_the_restart(self):
        sessions = [{"type": "RAC", "number": None, "id": "a"}, {"type": "RAC", "number": 2, "id": "b"}]
        self.assertEqual(pr.final_session(sessions, "RAC")["id"], "b")
        self.assertEqual(pr.final_session([{"type": "RAC", "number": None, "id": "a"}], "RAC")["id"], "a")

    def test_grid_penalty_and_non_starter(self):
        rows = [q(1, "QNR2", 93, 1), q(2, "QNR2", 89, 2), q(3, "QNR2", 72, 3), q(4, "QNR1", 5, 3, final=13)]
        # 89 dropped back for a penalty, 72 did not start the Race
        plan = pr.plan_grid(rows, {"Race": [93, 5, 89]})
        self.assertIn((2, "finalPos", 3, "#89 Race grid 2 -> 3"), plan)
        self.assertIn((4, "finalPos", 2, "#5 Race grid 13 -> 2"), plan)
        self.assertIn((3, "finalPos", 4, "#72 Race grid 3 -> 4"), plan)
        self.assertEqual(pr.plan_grid(rows, {}), [])

    def test_no_change_when_stored_grid_is_official(self):
        rows = [q(1, "QNR2", 93, 1), q(2, "QNR2", 89, 2), q(4, "QNR1", 5, 3, final=3)]
        self.assertEqual(pr.plan_grid(rows, {"Race": [93, 89, 5], "Sprint": [93, 89, 5]}), [])

    def test_fastest_lap_rider_matched_by_name_with_accents(self):
        cls = [{"rider": {"number": 25, "full_name": "Raúl Fernández"}}, {"rider": {"number": 37, "full_name": "Pedro Acosta"}}]
        with mock.patch.object(pr, "pdf_text", return_value="Fastest Lap: Lap 6   Raul FERNANDEZ     1'38.100"):
            fl, msg = pr.sprint_fastest_lap({"status": "FINISHED", "session_files": {"classification": {"url": "x"}}}, cls)
        self.assertEqual(fl, (25, 6, "1'38.100"))
        with mock.patch.object(pr, "pdf_text", return_value="Fastest Lap: Lap 6   Someone ELSE     1'38.100"):
            fl, msg = pr.sprint_fastest_lap({"status": "FINISHED", "session_files": {"classification": {"url": "x"}}}, cls)
        self.assertIsNone(fl)

    def _api(self, sprint_files, race_status="NOT_STARTED"):
        sessions = [{"id": "spr", "type": "SPR", "number": None, "status": "FINISHED", "session_files": sprint_files},
                    {"id": "rac", "type": "RAC", "number": None, "status": race_status, "session_files": {}}]
        def api(path):
            if path == "seasons": return [{"year": 2026, "id": "s"}]
            if path.startswith("events"): return [{"short_name": "POR", "id": "e"}]
            if path.startswith("sessions"): return sessions
            if path.startswith("session/spr"): return {"classification": [{"rider": {"number": 93, "full_name": "Marc Marquez"}, "points": 12}]}
            raise AssertionError(path)
        return api

    def _rows(self):
        def row(i, typ, num, pos, fl=None):
            return {"id": i, "attributes": {"position": pos, "finalPos": None, "sprintFinalPos": None, "fastestLap": fl,
                    "race": {"data": {"attributes": {"type": typ}}}, "seasonGrid": {"data": {"attributes": {"driverNumber": num}}}}}
        rows = [row(1, "QNR2", 93, 1), row(2, "QNR2", 89, 2), row(9, "Sprint", 93, 1)]
        self.stored = {r["id"]: r for r in rows}
        return lambda gid: list(self.stored.values())

    def _write(self, writes):
        def w(row, fields):
            writes.append((row, fields))
            self.stored[row]["attributes"].update(fields)
        return w

    def test_run_gp_writes_grid_and_fastest_lap(self):
        writes = []
        files = {"grid": {"url": "g"}, "classification": {"url": "c"}}
        texts = {"g": "\n".join(f"{n}Rider{chr(65+i)}NAME" for i, n in enumerate([89, 93, 1, 2, 3, 4, 5, 6, 7, 8, 9])),
                 "c": "Pos Pts # Rider Nation Team\n 1 12 93 Marc MARQUEZ    SPA Ducati Lenovo Team\n"
                      "Fastest Lap: Lap 7   Marc MARQUEZ    1'52.218"}
        with mock.patch.object(pr, "pdf_text", side_effect=lambda url, layout: texts[url]):
            changed, pending, problems = pr.run_gp({"id": "47", "shortName": "POR", "year": "2026"},
                                                   {"Sprint": NOW - timedelta(hours=1)}, NOW, self._api(files),
                                                   self._rows(), self._write(writes))
        self.assertTrue(changed); self.assertEqual((pending, problems), ([], []))
        self.assertIn((1, {"sprintFinalPos": 2}), writes)
        self.assertIn((2, {"sprintFinalPos": 1}), writes)
        self.assertIn((9, {"fastestLap": True, "fastestLapNo": 7, "fastestLapTime": "1'52.218"}), writes)
        self.assertIn((9, {"points": 12}), writes)  # stored without points, API and PDF agree on 12

    def test_missing_pdf_is_pending_then_reported(self):
        for age, expect_pending in ((1, True), (10, False)):
            changed, pending, problems = pr.run_gp({"id": "47", "shortName": "POR", "year": "2026"},
                                                   {"Sprint": NOW - timedelta(hours=age)}, NOW, self._api({}),
                                                   self._rows(), lambda r, f: None)
            self.assertFalse(changed)
            self.assertEqual(bool(pending), expect_pending); self.assertEqual(bool(problems), not expect_pending)


if __name__ == "__main__":
    unittest.main()


class CorrectionsTest(unittest.TestCase):
    from cron.data_upload.moto_gp import corrections as C

    def _rows(self):
        return [{"id": i, "number": n, "position": i, "points": p, "laps": 20, "time": t, "dnf": False}
                for i, (n, p, t) in enumerate([(93, 25, "41:00.000"), (89, 20, "41:01.000"), (72, 16, "41:02.000")], start=1)]

    def _pdf(self, order):
        return [{"pos": i if not nc else None, "pts": pts, "num": n, "name": "", "nc": nc, "ms": ms}
                for i, (n, pts, nc, ms) in enumerate(order, start=1)]

    def test_post_race_penalty_moves_rider_and_points(self):
        # #89 gets a time penalty after the race: drops to P3, points 16; #72 up to P2 with 20
        cls = [{"rider": {"number": 93}, "points": 25, "time": "41:00.000", "total_laps": 20},
               {"rider": {"number": 72}, "points": 20, "time": "41:02.000", "total_laps": 20},
               {"rider": {"number": 89}, "points": 16, "time": "41:04.000", "total_laps": 20}]
        pdf = self._pdf([(93, 25, False, 2460000), (72, 20, False, 2462000), (89, 16, False, 2464000)])
        fixes, held = self.C.plan_session("Race", cls, self._rows(), pdf)
        got = {(r, f): v for r, f, v, _ in fixes}
        self.assertEqual(got[(2, "position")], 3); self.assertEqual(got[(3, "position")], 2)
        self.assertEqual(got[(2, "points")], 16); self.assertEqual(got[(3, "points")], 20)
        self.assertEqual(got[(2, "time")], "41:04.000"); self.assertEqual(held, [])

    def test_sources_disagree_nothing_written(self):
        cls = [{"rider": {"number": 93}, "points": 25, "time": "41:00.000", "total_laps": 20}]
        pdf = self._pdf([(93, 20, False, 2460000)])  # PDF says 20 points, API 25
        fixes, held = self.C.plan_session("Race", cls, self._rows()[:1], pdf)
        self.assertEqual([f for f in fixes if f[1] == "points"], []); self.assertTrue(held)

    def test_non_classified_order_and_dnf_from_pdf(self):
        rows = self._rows()
        cls = [{"rider": {"number": 93}, "points": 25, "time": "41:00.000", "total_laps": 20},
               {"rider": {"number": 72}, "points": 0, "time": None, "total_laps": 3},
               {"rider": {"number": 89}, "points": 0, "time": None, "total_laps": 5}]
        pdf = self._pdf([(93, 25, False, 2460000), (72, 0, True, None), (89, 0, True, None)])
        fixes, held = self.C.plan_session("Race", cls, rows, pdf)
        got = {(r, f): v for r, f, v, _ in fixes}
        self.assertEqual(got[(3, "position")], 2); self.assertEqual(got[(2, "position")], 3)
        self.assertTrue(got[(2, "dnf")]); self.assertTrue(got[(3, "dnf")])


class OwedRecomputeTest(unittest.TestCase):
    """Reviewer case: rows corrected, then the stats call fails. The recompute must still happen."""
    def setUp(self):
        logger.remove()
        pr._state.clear()

    def test_failed_stats_after_a_write_is_retried(self):
        from datetime import datetime, timedelta, timezone
        now = datetime(2026, 11, 22, 15, 0, tzinfo=timezone.utc)
        races = [{"id": "606", "attributes": {"type": "Race", "startTime": "2026-11-22T13:00:00.000Z", "grandPrix": {"data": {
            "id": "47", "attributes": {"shortName": "POR", "isCancelled": None, "season": {"data": {"attributes": {"year": "2026"}}}}}}}}]
        calls = {"run_gp": 0, "stats": 0}
        def run_gp(gp, started, now, api, fetch_rows, write, apply=True):
            calls["run_gp"] += 1
            if calls["run_gp"] == 1:
                write("1", {"position": 2})
                raise TimeoutError("read timeout after the write")
            return False, [], []
        def stats(season_year):
            calls["stats"] += 1
            if calls["stats"] == 1:
                raise ConnectionError("strapi blip")
        import cron.strapi_api.apis as apis
        import cron.stats_calc.moto_gp.moto_gp_stats_update as su
        with mock.patch.object(apis, "get_races_starting_between", return_value=races), \
             mock.patch.object(apis, "update_race_result"), mock.patch.object(apis, "update_config_for_race_result") as cache, \
             mock.patch.object(su, "process_update_moto_gp_stats", side_effect=stats), \
             mock.patch.object(pr, "run_gp", side_effect=run_gp), mock.patch.object(pr, "fetch_standings_diffs", return_value=[]):
            run = pr.make_pass()
            pending1, probs1 = run(now)                          # write, timeout, stats fail
            pending2, probs2 = run(now + timedelta(minutes=2))  # within the 15 min throttle: recompute only
            pending3, _ = run(now + timedelta(minutes=4))
        self.assertTrue(pending1); self.assertTrue(probs1)
        self.assertEqual(calls["stats"], 2)                      # retried once, then done
        self.assertEqual(cache.call_count, 1)
        self.assertEqual(calls["run_gp"], 1)                     # throttle kept for the corrections themselves
        self.assertFalse(pr._state["47"]["stats_owed"])


class PartsAndPdfTest(unittest.TestCase):
    from cron.data_upload.moto_gp import corrections as C

    HEAD = "   Pos Pts # Rider                                         Nation Team                      Motorcycle   Total Time   Km/h   Gap"

    def test_half_points_rows_parse(self):
        text = "\n".join([self.HEAD,
            "      1   12.5      73 Alex MARQUEZ                       SPA BK8 Gresini Racing MotoGP    DUCATI     20'02.258   167.3",
            "      2     10      37 Pedro ACOSTA                       SPA Red Bull KTM Factory Racing  KTM        20'02.299   167.3  0.041",
            "      3      8      49 Fabio DI GIANNANTONIO              ITA Pertamina Enduro VR46 Racing DUCATI     20'02.715   167.2  0.457",
            "     16       5 Johann ZARCO                              FRA CASTROL Honda LCR            HONDA      20'30.000   160.0  27.742"])
        rows = self.C.parse_session_pdf(text)
        self.assertEqual([(r["pos"], r["pts"], r["num"]) for r in rows], [(1, 12.5, 73), (2, 10, 37), (3, 8, 49), (16, 0, 5)])

    def test_not_on_restart_grid_counts_as_not_classified(self):
        text = "\n".join([self.HEAD,
            "      1     25      73 Alex MARQUEZ                       SPA BK8 Gresini Racing MotoGP    DUCATI     41'02.258   167.3",
            "   Not on restart grid",
            "            93 Marc MARQUEZ                               SPA Ducati Lenovo Team           DUCATI",])
        rows = self.C.parse_session_pdf(text)
        self.assertEqual([(r["num"], r["nc"]) for r in rows], [(73, False), (93, True)])

    def test_abandoned_restart_keeps_part_one(self):
        sessions = [{"id": "a", "type": "RAC", "number": None, "status": "FINISHED"},
                    {"id": "b", "type": "RAC", "number": 2, "status": "CANCELLED"}]
        self.assertEqual(self.C.final_api_session(sessions, "Race")["id"], "a")
        self.assertEqual(pr.final_session(sessions, "RAC")["id"], "a")
        sessions[1]["status"] = "FINISHED"
        self.assertEqual(self.C.final_api_session(sessions, "Race")["id"], "b")
        self.assertEqual(pr.final_session(sessions, "RAC")["id"], "b")
        from cron.moto_gp import moto_gp_api as m
        from unittest import mock
        for status, want in (("CANCELLED", "a"), ("FINISHED", "b")):
            sessions[1]["status"] = status
            with mock.patch.object(m.requests, "get", return_value=mock.Mock(json=lambda: sessions, raise_for_status=lambda: None)):
                self.assertEqual(m.fetch_session("Race", "ev"), want)

