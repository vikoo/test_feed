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

    def test_country_uses_the_strapi_short_name(self):
        self.assertEqual(ag.country_name({"country": {"iso": "GB", "name": "United Kingdom of Great Britain and Northern Ireland"}}), "UK")
        self.assertEqual(ag.country_name({"country": {"iso": "ES", "name": "Spain"}}), "Spain")
        self.assertIsNone(ag.country_name({}))

    def test_two_rider_records_with_the_same_name_create_nothing(self):
        st = FakeStrapi([{"id": 40, "attributes": {"lastName": "J. Dixon", "number": 7}},
                         {"id": 41, "attributes": {"lastName": "J. Dixon", "number": 8}}])
        created, problems = ag.plan_and_create("2026", "QAT", [96], api, st, apply=True, now_iso="t")
        self.assertEqual(created, []); self.assertEqual(st.calls, []); self.assertIn("2 rider records", problems[0])
        st = FakeStrapi([{"id": 40, "attributes": {"lastName": "J. Dixon", "number": 96}},
                         {"id": 41, "attributes": {"lastName": "J. Dixon", "number": 8}}])
        ag.plan_and_create("2026", "QAT", [96], api, st, apply=True, now_iso="t")
        self.assertEqual(next(c for c in st.calls if c[1] == "season-grids")[2]["driver"], 40)  # the same number wins

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

    def test_never_duplicates_a_number_that_has_a_current_grid(self):
        st = FakeStrapi([])
        created, problems = ag.plan_and_create("2026", "QAT", [10], api, st, apply=True, now_iso="t")
        self.assertEqual(created, []); self.assertEqual(st.calls, []); self.assertIn("exists", problems[0])

    def test_team_link_failure_keeps_the_grid_and_says_what_to_do(self):
        st = FakeStrapi([{"id": 40, "attributes": {"lastName": "J. Dixon"}}])
        def put(path, data): raise ConnectionError("strapi blip")
        st.put = put
        with mock.patch.object(ag.time, "sleep"):
            created, problems = ag.plan_and_create("2026", "QAT", [96], api, st, apply=True, now_iso="t")
        self.assertEqual([c["grid"] for c in created], [500])  # grid exists: cache bump and ingest still happen
        self.assertTrue(any("link it to team standing 31 by hand" in p for p in problems))

    def test_grid_post_failure_creates_nothing_more(self):
        st = FakeStrapi([{"id": 40, "attributes": {"lastName": "J. Dixon"}}])
        orig = st.post
        def post(path, data):
            if path == "season-grids": raise ConnectionError("down")
            return orig(path, data)
        st.post = post
        created, problems = ag.plan_and_create("2026", "QAT", [96], api, st, apply=True, now_iso="t")
        self.assertEqual(created, []); self.assertFalse(any(c[0] == "put" for c in st.calls))
        self.assertTrue(any("season grid creation failed" in p for p in problems))

    def test_handler_bumps_both_grid_cache_keys(self):
        posted = []
        def post(url, json=None, **kw):
            posted.append(json["variables"]["input"])
            return mock.Mock(raise_for_status=lambda: None, json=lambda: {"data": {}})
        with mock.patch.object(ag.requests, "post", side_effect=post):
            ag._bump_grid_cache()
        self.assertEqual([list(p) for p in posted], [["driverTeamTrackSeasonTyre"], ["chassisSeasonGrid"]])


class NewTeamTest(unittest.TestCase):
    """A rider of a team that has nobody in Strapi: same-make factory bike, no team link, session not blocked."""
    def setUp(self):
        logger.remove()

    def _api(self, make):
        def f(path):
            if path.startswith("session/r"):
                return {"classification": [{"rider": {"number": 77, "full_name": "New Rider", "country": {"iso": "ES", "name": "Spain"}},
                                             "team": {"name": "Brand New Racing"}, "constructor": {"name": make}},
                                            {"rider": {"number": 10, "full_name": "Luca Marini"}, "team": {"name": "Honda HRC Castrol"},
                                             "constructor": {"name": "Honda"}}]}
            return api(path)
        return f

    class Strapi(FakeStrapi):
        def get(self, path, params=None):
            if path == "season-grids":
                ch = lambda i, n, pu: {"data": {"id": i, "attributes": {"name": n, "powerUnit": pu}}}
                return {"data": [{"id": 78, "attributes": {"driverNumber": 10, "teamColor": "#e50000", "isOldGrid": None, "chassis": ch(37, "Factory Honda RC213V", "Honda")}},
                                 {"id": 70, "attributes": {"driverNumber": 5, "teamColor": "#ffffff", "isOldGrid": None, "chassis": ch(39, "LCR Honda RC213V", "Honda")}},
                                 {"id": 99, "attributes": {"driverNumber": 6, "teamColor": "#000000", "isOldGrid": None, "chassis": ch(43, "Factory Honda RC213V Test", "Honda")}}]}
            return super().get(path, params)

    def test_new_team_gets_the_factory_bike_and_no_team_link(self):
        st = self.Strapi([])
        created, problems = ag.plan_and_create("2026", "QAT", [77], self._api("Honda"), st, apply=True, now_iso="t")
        grid = next(c for c in st.calls if c[1] == "season-grids")[2]
        self.assertEqual((grid["chassis"], grid["teamColor"], grid["driverPhoto"]), (37, "#e50000", ag.DEFAULT_PHOTO))
        self.assertFalse(any(c[0] == "put" for c in st.calls))  # no team standing to link to
        self.assertEqual(created[0]["decision"], "unclear"); self.assertIn("New team", problems[-1])

    def test_new_manufacturer_is_left_to_a_person(self):
        st = self.Strapi([])
        created, problems = ag.plan_and_create("2026", "QAT", [77], self._api("BMW"), st, apply=True, now_iso="t")
        self.assertEqual(created, []); self.assertEqual(st.calls, []); self.assertIn("no bike of this make", problems[0])


if __name__ == "__main__":
    unittest.main()
