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
