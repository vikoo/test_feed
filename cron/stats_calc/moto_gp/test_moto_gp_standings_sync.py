import unittest
from unittest import mock

from loguru import logger

from cron.stats_calc.moto_gp import moto_gp_standings_sync as sync
from cron.stats_calc.moto_gp.test_moto_gp_tie_break import res


def standing(sid, grid, number, extra=None, season_id=6):
    attrs = {
        "position": sid,
        "season": {"data": {"id": season_id}},
        "seasonGrid": {"data": {"id": grid, "attributes": {"driverNumber": number}}},
    }
    if extra:
        attrs["grids"] = {"data": [{"id": g, "attributes": {"driverNumber": n}} for g, n in extra]}
    return {"id": sid, "attributes": attrs}


def official(*numbers):
    return {"classification": {"rider": [{"rider": {"number": n}} for n in numbers]}}


class Recorder:
    def __init__(self, exists=False, fail_for=()):
        self.created = []
        self._exists = exists
        self._fail_for = fail_for

    def exists(self, grid_id):
        return self._exists

    def create(self, season_id, grid_id, position):
        if grid_id in self._fail_for:
            raise RuntimeError("boom")
        self.created.append((season_id, grid_id, position))
        return f"new{len(self.created)}"


def run_ensure(standings, official_payload, grids_by_number, recorder, team_standings=()):
    return sync.ensure_driver_standings(
        standings, list(team_standings),
        fetch_official=lambda: official_payload,
        fetch_grids=lambda: grids_by_number,
        exists=recorder.exists,
        create=recorder.create,
    )


class PlanTest(unittest.TestCase):
    def test_numbers_cover_primary_and_extra_grids(self):
        s = [standing(1, 10, 93), standing(2, 20, 5, extra=[(20, 5), (21, 5)])]
        self.assertEqual(sync.standing_driver_numbers(s), {93, 5})

    def test_nothing_missing(self):
        s = [standing(1, 10, 93), standing(2, 20, 5)]
        self.assertEqual(sync.plan_missing_driver_standings([93, 5], s, {93: [10], 5: [20]}), ([], []))

    def test_substitute_with_one_grid_is_created(self):
        s = [standing(1, 10, 93)]
        plan = sync.plan_missing_driver_standings([93, 15], s, {93: [10], 15: [95]})
        self.assertEqual(plan, ([(15, 95)], []))

    def test_rider_with_two_active_grids_is_not_treated_as_missing(self):
        # Real 2026 data: #51 Pirro has grids 86 (standing 83) and 90 (no standing).
        s = [standing(83, 86, 51)]
        self.assertEqual(sync.plan_missing_driver_standings([51], s, {51: [86, 90]}), ([], []))

    def test_missing_rider_with_two_active_grids_is_skipped(self):
        plan = sync.plan_missing_driver_standings([15], [], {15: [95, 96]})
        self.assertEqual(plan[0], [])
        self.assertIn("more than one", plan[1][0][1])

    def test_missing_rider_without_grid_is_skipped(self):
        plan = sync.plan_missing_driver_standings([15], [], {})
        self.assertEqual(plan, ([], [(15, "no active season grid")]))

    def test_too_many_missing_creates_nothing(self):
        grids = {n: [100 + n] for n in range(1, 6)}
        to_create, skipped = sync.plan_missing_driver_standings(list(range(1, 6)), [], grids)
        self.assertEqual(to_create, [])
        self.assertEqual(len(skipped), 5)

    def test_official_numbers_parsing(self):
        self.assertEqual(sync.official_rider_numbers(official(93, 5)), [93, 5])
        self.assertEqual(sync.official_rider_numbers(None), [])
        self.assertEqual(sync.official_rider_numbers({"classification": {}}), [])


class EnsureTest(unittest.TestCase):
    def test_creates_missing_row_and_returns_it_in_memory(self):
        s = [standing(1, 10, 93)]
        rec = Recorder()
        out = run_ensure(s, official(93, 15), {93: [10], 15: [95]}, rec)
        self.assertEqual(rec.created, [(6, 95, 2)])
        self.assertEqual(len(out), 2)
        self.assertEqual(out[1]["id"], "new1")
        self.assertEqual(out[1]["attributes"]["seasonGrid"]["data"]["id"], 95)
        self.assertEqual(len(s), 1, "input list is not mutated")

    def test_existing_row_found_by_check_is_not_duplicated(self):
        s = [standing(1, 10, 93)]
        rec = Recorder(exists=True)
        out = run_ensure(s, official(93, 15), {93: [10], 15: [95]}, rec)
        self.assertEqual(rec.created, [])
        self.assertEqual(out, s)

    def test_create_failure_does_not_raise_and_next_rider_is_still_tried(self):
        s = [standing(1, 10, 93)]
        rec = Recorder(fail_for=(95,))
        out = run_ensure(s, official(93, 15, 16), {93: [10], 15: [95], 16: [96]}, rec)
        self.assertEqual(rec.created, [(6, 96, 2)])
        self.assertEqual([x["id"] for x in out], [1, "new1"])

    def test_official_fetch_failure_returns_existing_rows(self):
        s = [standing(1, 10, 93)]

        def boom():
            raise RuntimeError("pulselive down")

        out = sync.ensure_driver_standings(s, [], boom, lambda: {}, lambda g: False, Recorder().create)
        self.assertEqual(out, s)

    def test_empty_official_table_does_nothing(self):
        s = [standing(1, 10, 93)]
        fetch_grids = mock.Mock()
        out = sync.ensure_driver_standings(s, [], lambda: official(), fetch_grids, lambda g: False, Recorder().create)
        self.assertEqual(out, s)
        fetch_grids.assert_not_called()

    def test_no_season_id_creates_nothing(self):
        rec = Recorder()
        out = run_ensure([], official(15), {15: [95]}, rec)
        self.assertEqual((out, rec.created), ([], []))

    def test_warns_when_created_rider_is_not_in_a_team_standing(self):
        messages = []
        sink = logger.add(lambda m: messages.append(str(m)), level="WARNING")
        try:
            run_ensure([standing(1, 10, 93)], official(93, 15), {93: [10], 15: [95]}, Recorder())
        finally:
            logger.remove(sink)
        self.assertTrue(any("not linked to any team standing" in m for m in messages))

    def test_no_warning_when_rider_is_already_in_a_team_standing(self):
        messages = []
        sink = logger.add(lambda m: messages.append(str(m)), level="WARNING")
        team = {"attributes": {"seasonGrid": {"data": [{"id": 95}]}}}
        try:
            run_ensure([standing(1, 10, 93)], official(93, 15), {93: [10], 15: [95]}, Recorder(), [team])
        finally:
            logger.remove(sink)
        self.assertFalse(any("not linked to any team standing" in m for m in messages))


class UncountedGridsTest(unittest.TestCase):
    def test_pirro_style_split_grid_is_reported(self):
        s = [standing(83, 86, 51)]
        results = [res(18, 7, rtype="Sprint", grid=90), res(19, 7, grid=90), res(19, 3, grid=86)]
        self.assertEqual(sync.uncounted_result_grids(results, s), {90: 2})

    def test_practice_results_and_extra_grids_are_not_reported(self):
        s = [standing(83, 86, 51, extra=[(86, 51), (90, 51)])]
        results = [res(1, 1, rtype="FP1", grid=77), res(19, 7, grid=90)]
        self.assertEqual(sync.uncounted_result_grids(results, s), {})


class EndToEndTest(unittest.TestCase):
    def test_new_substitute_is_ranked_in_the_same_run(self):
        from cron.stats_calc.moto_gp.moto_gp_stats_update_utils import update_moto_gp_stats

        s = [standing(1, 1, 93), standing(2, 2, 35)]
        results = [res(1, 1, grid=1, points=25), res(16, 1, grid=2), res(14, 1, rtype="Sprint", grid=3)]
        out = run_ensure(s, official(93, 35, 15), {93: [1], 35: [2], 15: [3]}, Recorder())
        with mock.patch("cron.stats_calc.moto_gp.moto_gp_stats_update_utils.update_driver_standings") as upd, \
                mock.patch("cron.stats_calc.moto_gp.moto_gp_stats_update_utils.update_team_standings"):
            update_moto_gp_stats("2026", results, out, [])
        uploaded = {c.kwargs["row_id"]: c.kwargs["driver_map"]["position"] for c in upd.call_args_list}
        self.assertEqual(uploaded, {1: 1, 2: 2, "new1": 3})

    def test_entrypoint_creates_rows_before_the_stats_update(self):
        from cron.stats_calc.moto_gp import moto_gp_stats_update as entry

        s, t = [standing(1, 10, 93)], []
        calls = []
        with mock.patch.object(entry, "fetch_all_race_results", return_value=[]), \
                mock.patch.object(entry, "fetch_driver_team_standings_for_season", return_value=(s, t)), \
                mock.patch.object(entry, "fetch_season", return_value="uuid"), \
                mock.patch.object(entry, "fetch_rider_standings", return_value=official(93, 15)), \
                mock.patch.object(entry, "get_active_season_grids_by_number", return_value={93: [10], 15: [95]}), \
                mock.patch.object(entry, "driver_standing_exists_for_grid", return_value=False), \
                mock.patch.object(entry, "create_driver_standing", return_value="new1"), \
                mock.patch.object(entry, "update_moto_gp_stats", side_effect=lambda *a: calls.append(a)), \
                mock.patch.object(entry, "process_constructor_stats_update"), \
                mock.patch.object(entry, "update_config_for_stats"):
            entry.process_update_moto_gp_stats("2026")
        self.assertEqual([x["id"] for x in calls[0][2]], [1, "new1"])


if __name__ == "__main__":
    unittest.main()
