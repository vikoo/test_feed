import unittest
from unittest import mock

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
        self.assertEqual(ts.choose(32, None, GRID, [99], TEAM_OF, counted={99}), ("keep", 99))

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
        cons = {47: "Yamaha", 43: "Yamaha", 7: "Yamaha"}
        self.assertEqual(ts.plan_session(s, [s] * 7, grid, team_of, {47: [88, 97]}, cons), {47: ("wildcard", None, "use", 88)})
        self.assertEqual(ts.plan_session(s, [s] * 7, grid, team_of, {47: [88, 97]}),
                         {47: ("unclear", None, "keep", 97)})  # make unknown: reported, never moved

    def test_lcr_two_names_two_riders_is_no_extra_rider(self):
        self.assertEqual(ts.plan_session(POR, [POR] * 7, GRID, TEAM_OF, {5: [82], 11: [83], 27: [92]}),
                         {27: ("substitute", 24, "create", None)})

    def test_test_team_is_a_wild_card(self):
        s = [(51, "Ducati Test Team"), (93, DUC)]
        self.assertEqual(ts.decide(51, [s], GRID, TEAM_OF), ("wildcard", None))


MAKES = {93: "Ducati", 63: "Ducati", 27: "Ducati", 73: "Ducati", 54: "Ducati", 5: "Honda", 11: "Honda", 49: "Ducati", 21: "Ducati"}


class FakeStrapi:
    """2026 Strapi as REST returns it (int ids). fail: {"post"|"team"|"driver"} makes that write raise once."""

    def __init__(self, extra_grids=(), fail=()):
        self.posts, self.puts, self.fail = [], [], set(fail)
        self.grids = [self.g(64, 93, 30, "#c00"), self.g(65, 63, 30, "#c00"), self.g(66, 73, 31, "#9ba"),
                      self.g(67, 54, 31, "#9ba"), self.g(92, 27, 31, "#9ba"), self.g(82, 5, 40, "#fff"),
                      self.g(83, 11, 40, "#fff"), self.g(68, 49, 50, "#ff0"), self.g(69, 21, 50, "#ff0")] + list(extra_grids)
        self.teams = {24: [64, 65], 25: [66, 67, 92], 33: [82, 83], 26: [68, 69]}
        self.drivers = {7: (64, []), 90: (92, [])}
        self.next_id = 101

    @staticmethod
    def g(i, n, ch, color, old=None, driver=None):
        return {"id": i, "attributes": {"driverNumber": n, "teamColor": color, "isOldGrid": old,
                                        "chassis": {"data": {"id": ch}}, "driver": {"data": {"id": driver or 1000 + n}}}}

    def get(self, path, params=None):
        page = lambda data: {"data": data, "meta": {"pagination": {"pageCount": 1}}}
        if path == "seasons":
            return {"data": [{"id": 6}]}
        if path == "season-grids":
            return page(self.grids)
        if path == "team-standings":
            return page([{"id": t, "attributes": {"seasonGrid": {"data": [{"id": x} for x in gs]}}} for t, gs in self.teams.items()])
        if path == "driver-standings":
            return page([{"id": i, "attributes": {"seasonGrid": {"data": {"id": p}}, "grids": {"data": [{"id": x} for x in gs]}}}
                         for i, (p, gs) in self.drivers.items()])
        raise AssertionError(path)

    def post(self, path, data):
        if "post" in self.fail:
            self.fail.discard("post"); raise RuntimeError("502")
        self.posts.append((path, data))
        gid, self.next_id = self.next_id, self.next_id + 1
        self.grids.append(self.g(gid, data["driverNumber"], data["chassis"], data["teamColor"], data.get("isOldGrid"), data["driver"]))
        return {"id": gid}

    def put(self, path, data):
        kind = "team" if path.startswith("team") else "driver"
        if kind in self.fail:
            self.fail.discard(kind); raise RuntimeError("502")
        self.puts.append((path, data))
        i = int(path.split("/")[1])
        if kind == "team":
            self.teams[i] = list(data["seasonGrid"])
        else:
            self.drivers[i] = (self.drivers[i][0], list(data["grids"]))


def cls(rows):
    return [{"rider": {"number": n}, "team": {"name": t}, "constructor": {"name": MAKES.get(n)}} for n, t in rows]


def fake_api(weekend):
    """pulselive with the given sessions (list of rows) as the finished sessions of POR."""
    types = ["FP", "PR", "FP", "Q", "Q", "SPR", "RAC"]
    nums = [1, None, 2, 1, 2, None, None]
    sessions = [{"id": f"s{i}", "type": types[i], "number": nums[i], "status": "FINISHED"} for i in range(len(weekend))]

    def api(path):
        if path == "seasons":
            return [{"year": 2026, "id": "S"}]
        if path.startswith("events"):
            return [{"short_name": "POR", "id": "E"}]
        if path.startswith("sessions"):
            return sessions
        i = int(path.split("/")[1][1:])
        return {"classification": cls(weekend[i])}
    return api


STR_GRID = {n: str(g) for n, g in GRID.items()}  # the uploader's map comes from GraphQL: string ids


class TeamCheckTest(unittest.TestCase):
    def run_check(self, strapi, weekend, session, grid=None, check=None):
        check = check or ts.TeamCheck(strapi, fake_api(weekend), "2026-11-20T11:00:00.000Z", lambda: None)
        return check.check("2026", "POR", cls(session), dict(grid or STR_GRID))

    def test_portugal_string_ids_create_a_ducati_grid_for_lecuona(self):
        strapi = FakeStrapi()
        grid, problems = self.run_check(strapi, [POR] * 7, POR)
        self.assertEqual(grid[27], 101)
        self.assertEqual(grid[93], "64")  # untouched, same type as the uploader gave
        path, body = strapi.posts[0]
        self.assertEqual((body["driverNumber"], body["chassis"], body["teamColor"], body["driver"], body["isOldGrid"]),
                         (27, 30, "#c00", 1027, True))  # Ducati bike and colour, same rider record
        self.assertEqual(strapi.teams[24], [64, 65, 101])
        self.assertEqual(strapi.drivers[90], (92, [92, 101]))
        self.assertEqual(len(problems), 1)
        self.assertIn("#27 rides for Ducati Lenovo Team (substitute): new season grid 101", problems[0])

    def test_seven_sessions_one_grid_one_report(self):
        strapi = FakeStrapi()
        check = ts.TeamCheck(strapi, fake_api([POR] * 7), "x", lambda: None)
        reports = []
        for _ in range(7):
            grid, problems = self.run_check(strapi, [POR] * 7, POR, check=check)
            self.assertEqual(grid[27], 101)
            reports += problems
        self.assertEqual((len(strapi.posts), len(reports)), (1, 1))

    def test_team_link_failure_is_completed_next_session_not_duplicated(self):
        strapi = FakeStrapi(fail={"team"})
        with mock.patch.object(ts.time, "sleep"):
            grid, problems = self.run_check(strapi, [POR] * 7, POR)
        self.assertEqual(grid[27], 101)
        self.assertEqual(strapi.teams[24], [64, 65, 101])  # retried inside the step
        strapi2 = FakeStrapi(extra_grids=[FakeStrapi.g(101, 27, 30, "#c00", old=True)])  # half made by an earlier run
        grid, problems = self.run_check(strapi2, [POR] * 7, POR)
        self.assertEqual((grid[27], strapi2.posts), (101, []))
        self.assertEqual(strapi2.teams[24], [64, 65, 101])
        self.assertEqual(strapi2.drivers[90], (92, [92, 101]))
        self.assertIn("grid 101 completed (team link, driver standing)", problems[0])

    def test_driver_standing_failure_reported_and_repaired_next_session(self):
        strapi = FakeStrapi(fail={"driver"})
        check = ts.TeamCheck(strapi, fake_api([POR] * 7), "x", lambda: None)
        grid, problems = self.run_check(strapi, [POR] * 7, POR, check=check)
        self.assertEqual(grid[27], 101)
        self.assertIn("driver standing step failed", problems[0])
        grid, problems = self.run_check(strapi, [POR] * 7, POR, check=check)
        self.assertEqual(strapi.drivers[90], (92, [92, 101]))
        self.assertEqual(len(strapi.posts), 1)

    def test_half_made_grid_in_the_map_is_completed_not_duplicated(self):
        # Main grid old (substitutes are marked old after their weekend): the map then gives the newest old
        # grid, here the half-made 101 (POST went through, the client saw an error).
        strapi = FakeStrapi(extra_grids=[FakeStrapi.g(101, 27, 30, "#c00", old=True)])
        grid, problems = self.run_check(strapi, [POR] * 7, POR, grid={**STR_GRID, 27: "101"})
        self.assertEqual((grid[27], strapi.posts), (101, []))
        self.assertEqual((strapi.teams[24], strapi.drivers[90]), ([64, 65, 101], (92, [92, 101])))

    def test_complete_grid_in_the_map_writes_nothing(self):
        strapi = FakeStrapi(extra_grids=[FakeStrapi.g(101, 27, 30, "#c00", old=True)])
        strapi.teams[24].append(101); strapi.drivers[90] = (92, [92, 101])
        grid, problems = self.run_check(strapi, [POR] * 7, POR, grid={**STR_GRID, 27: "101"})
        self.assertEqual((grid[27], strapi.posts, strapi.puts, problems), ("101", [], [], []))

    def test_another_riders_grid_with_the_same_number_is_never_used(self):
        strapi = FakeStrapi(extra_grids=[FakeStrapi.g(77, 27, 31, "#9ba", old=True, driver=5555)])
        grid, problems = self.run_check(strapi, [POR] * 7, POR)
        self.assertEqual((grid[27], len(strapi.posts)), (101, 1))  # a new grid, never 77
        self.assertEqual(strapi.drivers[90], (92, [92, 101]))

    def test_same_make_rider_at_a_team_with_an_open_seat_is_unclear(self):
        # HRC test rider #41 (grid linked to HRC) as "Castrol Honda LCR", Zarco out, both HRC riders racing.
        grid, team_of = {41: 96, 10: 78, 36: 79, 11: 83}, {96: 31, 78: 31, 79: 31, 83: 33}
        s = [(41, "Castrol Honda LCR"), (10, "Honda HRC Castrol"), (36, "Honda HRC Castrol"), (11, "Pro Honda LCR")]
        cons = {41: "Honda", 10: "Honda", 36: "Honda", 11: "Honda"}
        self.assertEqual(ts.plan_session(s, [s] * 7, grid, team_of, {41: [96]}, cons), {41: ("unclear", None, "keep", 96)})

    def test_weekend_unreadable_changes_nothing_and_reports(self):
        def down(path):
            raise RuntimeError("feed down")
        strapi = FakeStrapi()
        q = [(93, DUC), (27, DUC), (5, LCR)]  # a Q1 with Marquez and Lecuona only: misleading alone
        grid, problems = ts.TeamCheck(strapi, down).check("2026", "POR", cls(q), dict(STR_GRID))
        self.assertEqual((grid, strapi.posts, strapi.puts), (STR_GRID, [], []))
        self.assertIn("team check not applied", problems[0])

    def test_lecuona_as_lcr_substitute_on_another_make_is_unclear(self):
        lcr = [(93, DUC), (63, DUC), (73, GRES), (54, GRES), (27, LCR), (11, "Pro Honda LCR")]
        strapi = FakeStrapi()
        with mock.patch.dict(MAKES, {27: "Honda"}):
            grid, problems = self.run_check(strapi, [lcr] * 7, lcr)
        self.assertEqual((grid[27], strapi.posts), ("92", []))
        self.assertIn("unclear", problems[0])

    def test_no_suspect_no_write(self):
        strapi = FakeStrapi()
        normal = [(93, DUC), (63, DUC), (73, GRES), (54, GRES), (27, GRES)]
        grid, problems = self.run_check(strapi, [normal] * 7, normal)
        self.assertEqual((grid, problems, strapi.posts, strapi.puts), (STR_GRID, [], [], []))

    def test_strapi_down_keeps_the_map_and_reports(self):
        class Down(FakeStrapi):
            def get(self, path, params=None):
                raise RuntimeError("502")
        grid, problems = self.run_check(Down(), [POR] * 7, POR)
        self.assertEqual(grid, STR_GRID)
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

    def test_follow_up_problems_go_to_its_own_list(self):
        up.on_team_check = lambda y, g, c, m: (m, ["unclear #27"])
        sink = []
        up.team_checked("2026", "POR", [], {27: "92"}, sink=sink)
        self.assertEqual((sink, up.team_problems), (["unclear #27"], []))

    def test_no_hook_no_change(self):
        self.assertEqual(up.team_checked("2026", "POR", [], {27: 92}), {27: 92})


if __name__ == "__main__":
    unittest.main()
