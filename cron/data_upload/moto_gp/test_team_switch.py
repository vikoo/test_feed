import unittest

from cron.data_upload.moto_gp import moto_gp_data_upload as up
from cron.data_upload.moto_gp import team_switch as ts

DUC, GRES, LCR, VR46 = "Ducati Lenovo Team", "BK8 Gresini Racing MotoGP", "Castrol Honda LCR", "Pertamina Enduro VR46 Racing Team"
# 2026 Strapi: Ducati Lenovo standing 24 (Marquez #93 grid 64, Bagnaia #63 grid 65); Gresini 25 (A. Marquez #73
# grid 66, Aldeguer #54 grid 67, Lecuona #27 grid 92); LCR 33 (Zarco #5 grid 82, Moreira #11 grid 83);
# VR46 26 (#49 grid 68, #21 grid 69).
GRID = {93: 64, 63: 65, 73: 66, 54: 67, 27: 92, 5: 82, 11: 83, 49: 68, 21: 69, 32: 99}
TEAM_OF = {64: 24, 65: 24, 66: 25, 67: 25, 92: 25, 82: 33, 83: 33, 68: 26, 69: 26}
# Portugal 2026: Bagnaia out, Lecuona in the Ducati Lenovo seat.
POR = [(93, DUC), (27, DUC), (73, GRES), (54, GRES), (5, LCR), (11, "Pro Honda LCR"), (49, VR46), (21, VR46)]


class RuleTest(unittest.TestCase):
    def test_portugal_lecuona_is_the_only_suspect(self):
        self.assertEqual(ts.suspects(POR, GRID, TEAM_OF), [27])

    def test_portugal_lecuona_is_a_ducati_substitute(self):
        self.assertEqual(ts.decide(27, [POR] * 7, GRID, TEAM_OF), ("substitute", 24))
        self.assertEqual(ts.choose(27, 24, GRID, [92], TEAM_OF), ("create", None))

    def test_marc_marquez_is_never_moved(self):
        names = ts.names_to_standing(POR, GRID, TEAM_OF)
        self.assertEqual(names[DUC], 24)
        self.assertEqual(names[GRES], 25)

    def test_regular_weekend_no_suspect(self):
        normal = [(93, DUC), (63, DUC), (73, GRES), (54, GRES), (5, LCR), (11, "Pro Honda LCR")]
        self.assertEqual(ts.suspects(normal, GRID, TEAM_OF), [])

    def test_two_api_names_for_one_team_no_suspect(self):
        self.assertNotIn(LCR, ts.names_to_standing(POR, GRID, TEAM_OF))  # 1 vs 1: no name, never a false move

    def test_lecuona_back_at_gresini_reuses_grid_92(self):
        grid = {**GRID, 27: 101}
        team_of = {**TEAM_OF, 101: 24}
        back = [(93, DUC), (63, DUC), (27, GRES), (73, GRES)]  # Aldeguer out
        self.assertEqual(ts.suspects(back, grid, team_of), [27])
        self.assertEqual(ts.decide(27, [back] * 7, grid, team_of), ("substitute", 25))
        self.assertEqual(ts.choose(27, 25, grid, [92, 101], team_of), ("use", 92))

    def test_wild_card_on_an_unlinked_grid_stays(self):
        wc = [(93, DUC), (63, DUC), (32, DUC), (73, GRES), (54, GRES)]
        self.assertEqual(ts.suspects(wc, GRID, TEAM_OF), [32])
        self.assertEqual(ts.decide(32, [wc] * 7, GRID, TEAM_OF), ("wildcard", 24))
        self.assertEqual(ts.choose(32, None, GRID, [99], TEAM_OF), ("keep", 99))

    def test_wild_card_from_a_substitute_grid_moves_to_no_team(self):
        # Lecuona as a Ducati wild card with both Ducati riders present: no team counts his points.
        wc = [(93, DUC), (63, DUC), (27, DUC), (73, GRES), (54, GRES)]
        self.assertEqual(ts.decide(27, [wc] * 7, GRID, TEAM_OF), ("wildcard", 24))
        self.assertEqual(ts.choose(27, None, GRID, [92], TEAM_OF), ("create", None))

    def test_out_after_fp1_still_a_substitute(self):
        fp1 = [(93, DUC), (63, DUC), (27, DUC), (73, GRES), (54, GRES)]
        self.assertEqual(ts.decide(27, [fp1] + [POR] * 6, GRID, TEAM_OF), ("substitute", 24))

    def test_portugal_q1_lecuona_alone_does_not_name_his_old_team(self):
        q1 = [(27, DUC), (5, LCR), (11, "Pro Honda LCR")]  # Marquez, A. Marquez, Aldeguer went straight to Q2
        self.assertEqual(ts.decide(27, [POR, q1, POR], GRID, TEAM_OF), ("substitute", 24))
        plan = ts.plan_session(q1, [POR, q1, POR], GRID, TEAM_OF, {27: [92]})
        self.assertEqual(plan, {27: ("substitute", 24, "create", None)})

    def test_marquez_safe_in_a_session_with_only_lecuona_beside_him(self):
        only_two = [(93, DUC), (27, DUC)]
        weekend = [POR, only_two]
        self.assertEqual(ts.plan_session(only_two, weekend, GRID, TEAM_OF, {93: [64], 27: [92]}),
                         {27: ("substitute", 24, "create", None)})

    def test_test_team_entry_on_a_team_grid_is_checked(self):
        # Gardner, Japan 2024: wild card for the Yamaha test team, grid linked to Yamaha from his substitute rides.
        grid, team_of = {87: 47, 20: 9, 42: 10}, {47: 9, 9: 9, 10: 9}
        s = [(87, "Yamaha Test Team"), (20, "Monster Energy Yamaha MotoGP Team"), (42, "Monster Energy Yamaha MotoGP Team")]
        self.assertEqual(ts.plan_session(s, [s] * 7, grid, team_of, {87: [47, 98]}), {87: ("wildcard", None, "use", 98)})

    def test_yamaha_test_team_name_without_test_team(self):
        # A. Fernandez, Catalonia 2026: "Yamaha Factory Racing" wild card; his grid 97 counts for Pramac (34).
        grid, team_of = {47: 97, 43: 84, 7: 85}, {97: 34, 84: 34, 85: 34}
        s = [(47, "Yamaha Factory Racing"), (43, "Prima Pramac Yamaha MotoGP"), (7, "Prima Pramac Yamaha MotoGP")]
        self.assertEqual(ts.plan_session(s, [s] * 7, grid, team_of, {47: [88, 97]}), {47: ("wildcard", None, "use", 88)})

    def test_lcr_two_names_two_riders_is_no_extra_rider(self):
        self.assertEqual(ts.plan_session(POR, [POR] * 7, GRID, TEAM_OF, {5: [82], 11: [83], 27: [92]}),
                         {27: ("substitute", 24, "create", None)})

    def test_test_team_is_a_wild_card(self):
        s = [(51, "Ducati Test Team"), (93, DUC)]
        self.assertEqual(ts.decide(51, [s], GRID, TEAM_OF), ("wildcard", None))


class FakeStrapi:
    def __init__(self):
        self.posts, self.puts = [], []

    def get(self, path, params=None):
        if path == "seasons":
            return {"data": [{"id": 6}]}
        if path == "season-grids":
            def g(i, n, ch, color):
                return {"id": i, "attributes": {"driverNumber": n, "teamColor": color,
                                                "chassis": {"data": {"id": ch}}, "driver": {"data": {"id": 1000 + n}}}}
            return {"data": [g(64, 93, 30, "#c00"), g(65, 63, 30, "#c00"), g(66, 73, 31, "#9ba"), g(67, 54, 31, "#9ba"),
                             g(92, 27, 31, "#9ba"), g(82, 5, 40, "#fff"), g(83, 11, 40, "#fff")]}
        if path == "team-standings":
            t = lambda i, gs: {"id": i, "attributes": {"seasonGrid": {"data": [{"id": x} for x in gs]}}}
            return {"data": [t(24, [64, 65]), t(25, [66, 67, 92]), t(33, [82, 83])]}
        if path == "driver-standings":
            d = lambda i, p, gs: {"id": i, "attributes": {"seasonGrid": {"data": {"id": p}},
                                                          "grids": {"data": [{"id": x} for x in gs]}}}
            return {"data": [d(7, 64, []), d(90, 92, [])]}
        raise AssertionError(path)

    def post(self, path, data):
        self.posts.append((path, data))
        return {"id": 101}

    def put(self, path, data):
        self.puts.append((path, data))
        return {}


def cls(rows):
    return [{"rider": {"number": n}, "team": {"name": t}} for n, t in rows]


class TeamCheckTest(unittest.TestCase):
    def api(self, path):
        raise RuntimeError("feed down")  # weekend rows fall back to this session (tested on purpose)

    def test_portugal_creates_a_ducati_grid_for_lecuona(self):
        strapi, bumps = FakeStrapi(), []
        check = ts.TeamCheck(strapi, self.api, "2026-11-20T11:00:00.000Z", lambda: bumps.append(1))
        grid, problems = check.check("2026", "POR", cls(POR[:6]), dict(GRID))
        self.assertEqual(grid[27], 101)
        self.assertEqual(grid[93], 64)
        path, body = strapi.posts[0]
        self.assertEqual((path, body["driverNumber"], body["chassis"], body["teamColor"], body["driver"]),
                         ("season-grids", 27, 30, "#c00", 1027))  # Ducati bike and colour, same rider record
        self.assertIs(body["isOldGrid"], True)
        self.assertIn(("team-standings/24", {"seasonGrid": [64, 65, 101]}), strapi.puts)
        self.assertIn(("driver-standings/90", {"grids": [92, 101]}), strapi.puts)
        self.assertEqual(bumps, [1])
        self.assertEqual(len(problems), 1)
        self.assertIn("#27 rides for Ducati Lenovo Team (substitute): new season grid 101", problems[0])

    def test_no_suspect_no_write(self):
        strapi = FakeStrapi()
        normal = [(93, DUC), (63, DUC), (73, GRES), (54, GRES), (27, GRES)]
        grid, problems = ts.TeamCheck(strapi, self.api).check("2026", "POR", cls(normal), dict(GRID))
        self.assertEqual((grid, problems, strapi.posts, strapi.puts), (GRID, [], [], []))

    def test_strapi_down_keeps_the_map_and_reports(self):
        class Down(FakeStrapi):
            def get(self, path, params=None):
                raise RuntimeError("502")
        grid, problems = ts.TeamCheck(Down(), self.api).check("2026", "POR", cls(POR), dict(GRID))
        self.assertEqual(grid, GRID)
        self.assertIn("team check skipped", problems[0])


class UploaderHookTest(unittest.TestCase):
    def tearDown(self):
        up.on_team_check = None
        up.team_problems.clear()

    def test_hook_result_is_used_and_problems_kept(self):
        up.on_team_check = lambda y, g, c, m: ({**m, 27: 101}, ["moved"])
        self.assertEqual(up.team_checked("2026", "POR", [], {27: 92})[27], 101)
        self.assertEqual(up.team_problems, ["moved"])

    def test_hook_crash_keeps_the_map(self):
        def boom(*a):
            raise ValueError("x")
        up.on_team_check = boom
        self.assertEqual(up.team_checked("2026", "POR", [], {27: 92}), {27: 92})
        self.assertIn("team check failed", up.team_problems[0])

    def test_no_hook_no_change(self):
        self.assertEqual(up.team_checked("2026", "POR", [], {27: 92}), {27: 92})


if __name__ == "__main__":
    unittest.main()
