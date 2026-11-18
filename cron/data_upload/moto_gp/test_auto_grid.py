import unittest
from unittest import mock

from loguru import logger

from cron.data_upload.moto_gp import auto_grid as ag
from cron.data_upload.moto_gp import moto_gp_data_upload as up


class DecideTest(unittest.TestCase):
    # Honda HRC (team 31): Marini #10 grid 78, Mir #36 grid 79. LCR (33): Zarco #5 grid 70.
    grid_of = {10: 78, 36: 79, 5: 70, 72: 69, 89: 70_1}
    team_of = {78: 31, 79: 31, 70: 33, 69: 28, 70_1: 28}

    def test_qatar_dixon_replaces_absent_mir(self):
        sessions = [[(96, "Honda HRC Castrol"), (10, "Honda HRC Castrol"), (5, "LCR")]] * 7
        self.assertEqual(ag.decide(96, "Honda HRC Castrol", sessions, self.grid_of, self.team_of), ("substitute", 31))

    def test_japan_rider_out_after_fp1_still_a_substitute(self):
        fp1 = [(15, "Honda HRC Castrol"), (10, "Honda HRC Castrol"), (36, "Honda HRC Castrol")]
        rest = [(15, "Honda HRC Castrol"), (10, "Honda HRC Castrol")]
        self.assertEqual(ag.decide(15, "Honda HRC Castrol", [fp1] + [rest] * 6, self.grid_of, self.team_of), ("substitute", 31))

    def test_wild_card_with_both_regulars_present(self):
        s = [(32, "Aprilia Racing"), (72, "Aprilia Racing"), (89, "Aprilia Racing")]
        self.assertEqual(ag.decide(32, "Aprilia Racing", [s] * 7, self.grid_of, self.team_of), ("wildcard", None))

    def test_test_team_is_a_wild_card_and_no_mates_is_unclear(self):
        self.assertEqual(ag.decide(41, "Honda HRC Test Team", [[(41, "Honda HRC Test Team")]], {}, {}), ("wildcard", None))
        self.assertEqual(ag.decide(35, "Castrol Honda LCR", [[(35, "Castrol Honda LCR")]], self.grid_of, self.team_of), ("unclear", None))

    def test_strapi_last_name(self):
        self.assertEqual(ag.strapi_last_name("Jake Dixon"), "J. Dixon")


class FakeStrapi:
    def __init__(self, drivers):
        self.drivers, self.calls = drivers, []
    def get(self, path, params=None):
        if path == "seasons": return {"data": [{"id": 6}]}
        if path == "season-grids":
            return {"data": [{"id": 78, "attributes": {"driverNumber": 10, "teamColor": "#e50000", "isOldGrid": None, "chassis": {"data": {"id": 37}}}},
                             {"id": 79, "attributes": {"driverNumber": 36, "teamColor": "#e50000", "isOldGrid": None, "chassis": {"data": {"id": 37}}}}]}
        if path == "team-standings": return {"data": [{"id": 31, "attributes": {"seasonGrid": {"data": [{"id": 78}, {"id": 79}]}}}]}
        if path == "drivers": return {"data": self.drivers}
        raise AssertionError(path)
    def post(self, path, data):
        self.calls.append(("post", path, data)); return {"id": 500 if path == "season-grids" else 900}
    def put(self, path, data):
        self.calls.append(("put", path, data)); return {"id": 31}


def api(path):
    if path == "seasons": return [{"year": 2026, "id": "s"}]
    if path.startswith("events"): return [{"short_name": "QAT", "id": "e"}]
    if path.startswith("sessions"): return [{"id": "r", "type": "RAC", "number": None, "status": "FINISHED"}]
    if path.startswith("session/r"):
        return {"classification": [{"rider": {"number": 96, "full_name": "Jake Dixon", "country": {"name": "United Kingdom"}}, "team": {"name": "Honda HRC Castrol"}},
                                   {"rider": {"number": 10, "full_name": "Luca Marini"}, "team": {"name": "Honda HRC Castrol"}}]}
    raise AssertionError(path)


class CreateTest(unittest.TestCase):
    def setUp(self):
        logger.remove()

    def test_creates_grid_with_teammate_bike_default_photo_and_team_link(self):
        st = FakeStrapi([{"id": 40, "attributes": {"lastName": "J. Dixon"}}])
        created, problems = ag.plan_and_create("2026", "QAT", [96], api, st, apply=True, now_iso="t")
        grid = next(c for c in st.calls if c[1] == "season-grids")[2]
        self.assertEqual((grid["driver"], grid["chassis"], grid["teamColor"], grid["driverPhoto"]), (40, 37, "#e50000", ag.DEFAULT_PHOTO))
        self.assertIn(("put", "team-standings/31", {"seasonGrid": [78, 79, 500]}), st.calls)
        self.assertFalse(any(c[1] == "drivers" for c in st.calls))  # existing rider record reused
        self.assertEqual(len(problems), 1)

    def test_creates_the_rider_record_when_missing(self):
        st = FakeStrapi([])
        ag.plan_and_create("2026", "QAT", [96], api, st, apply=True, now_iso="t")
        drv = next(c for c in st.calls if c[1] == "drivers")[2]
        self.assertEqual((drv["lastName"], drv["number"], drv["country"]), ("J. Dixon", 96, "United Kingdom"))

    def test_uploader_creates_the_grid_then_ingests(self):
        calls = {"n": 0}
        def session(*a):
            calls["n"] += 1
            if calls["n"] == 1:
                raise up.MissingSeasonGridError([96])
            return "ingested"
        races = [{"id": "487", "attributes": {"type": "Race", "startTime": "2026-11-08T16:00:00.000Z",
                  "grandPrix": {"data": {"id": "46", "attributes": {"shortName": "QAT", "season": {"data": {"attributes": {"year": "2026"}}}}}}}}]
        handler = mock.Mock(return_value=(True, ["new season grid for #96"]))
        with mock.patch.object(up, "get_latest_past_race", return_value={"data": {"races": {"data": races}}}), \
             mock.patch.object(up, "_process_session", side_effect=session), mock.patch.object(up, "on_missing_grid", handler):
            s = up.process(now=up.parse_time("2026-11-08T18:00:00.000Z"))
        handler.assert_called_once_with("2026", "QAT", [96])
        self.assertEqual(len(s["ingested"]), 1); self.assertEqual(s["skipped_missing_grid"], [])


if __name__ == "__main__":
    unittest.main()
