"""Tests for the FIM Art. 1.28.7 tie-break. Groups below are real tie groups from the official standings."""
import unittest
from unittest import mock

from cron.stats_calc.moto_gp.moto_gp_tie_break import gp_tie_break_key


def res(pos, rnd, rtype="Race", dnf=False, final_pos=None, grid=1, points=0, classification=None):
    return {
        "attributes": {
            "position": pos,
            "finalPos": final_pos,
            "dnf": dnf,
            "points": points,
            "classification": {"data": {"attributes": {"type": classification}}} if classification else None,
            "seasonGrid": {"data": {"id": grid}},
            "race": {"data": {"attributes": {
                "type": rtype,
                "grandPrix": {"data": {"attributes": {"round": str(rnd)}}},
            }}},
        }
    }


def gp(positions, grid=1):
    return [res(p, i + 1, grid=grid) for i, p in enumerate(positions)]


def sprints(positions, grid=1):
    return [res(p, i + 1, rtype="Sprint", grid=grid) for i, p in enumerate(positions)]


def order(riders):
    """riders: {name: results}. Equal points assumed; returns names ranked by the tie-break key."""
    return sorted(riders, key=lambda n: gp_tie_break_key(riders[n]))


class TieBreakKeyTest(unittest.TestCase):
    def test_2024_zero_points_group(self):
        riders = {
            "Gardner": gp([17, 18, 19]) + sprints([18, 18, 20]),
            "Iannone": gp([17]) + sprints([19]),
            "Savadori": gp([18, 20, 21]) + sprints([15, 16, 17, 18, 18, 20, 21]),
            "Pirro": gp([20]) + sprints([21]),
        }
        self.assertEqual(order(riders), ["Gardner", "Iannone", "Savadori", "Pirro"])

    def test_2024_173_points_podium_beats_no_podium(self):
        riders = {
            "Morbidelli": gp([4, 5, 5, 5, 6, 6, 6, 7, 8, 8, 9, 10, 14, 18, 18]),
            "A Marquez": gp([3, 4, 4, 4, 6, 6, 7, 7, 7, 9, 9, 10, 10, 10, 15, 15]),
        }
        self.assertEqual(order(riders), ["A Marquez", "Morbidelli"])

    def test_2024_31_points_best_finish(self):
        riders = {
            "Nakagami": gp([11, 12, 13, 13, 13, 14, 14, 14, 14, 14, 14, 15, 16, 17, 17, 18, 19]),
            "Rins": gp([8, 9, 11, 13, 13, 13, 15, 15, 16, 16, 16, 19, 20, 21]),
        }
        self.assertEqual(order(riders), ["Rins", "Nakagami"])

    def test_2025_8_points(self):
        riders = {
            "A Fernandez": gp([13, 13, 14, 16, 16, 18, 18]),
            "Savadori": gp([9, 15, 16, 16, 16, 17, 17, 18, 18, 20]),
        }
        self.assertEqual(order(riders), ["Savadori", "A Fernandez"])

    def test_2025_zero_points(self):
        riders = {
            "Pirro": gp([17, 18]) + sprints([20, 20]),
            "A Espargaro": gp([16, 17, 17]) + sprints([16, 17, 18, 18, 19]),
        }
        self.assertEqual(order(riders), ["A Espargaro", "Pirro"])

    def test_2026_zero_points_sprint_only_rider_ranks_last(self):
        riders = {
            "Chantra": sprints([14]),
            "Pirro": gp([19, 19]) + sprints([18, 21]),
            "Savadori": gp([17]) + sprints([19]),
            "Folger": gp([16]),
            "Crutchlow": gp([16, 16, 17]) + sprints([18, 19, 19, 22]),
        }
        self.assertEqual(order(riders), ["Crutchlow", "Folger", "Savadori", "Pirro", "Chantra"])

    def test_sprint_results_never_break_a_tie(self):
        riders = {
            "sprint_winner": gp([10]) + sprints([1, 1, 1]),
            "gp_better": gp([9]),
        }
        self.assertEqual(order(riders), ["gp_better", "sprint_winner"])

    def test_countback_goes_deeper_than_best_finish(self):
        riders = {
            "one_p5": gp([5, 9]),
            "two_p5": gp([5, 5]),
        }
        self.assertEqual(order(riders), ["two_p5", "one_p5"])

    def test_identical_results_latest_best_round_wins(self):
        riders = {
            "early": [res(1, 3), res(4, 8)],
            "late": [res(1, 9), res(4, 2)],
        }
        self.assertEqual(order(riders), ["late", "early"])

    def test_non_classified_results_do_not_count(self):
        riders = {
            "crashed_p2": [res(2, 1, dnf=True), res(12, 2)],
            "steady": [res(11, 1), res(12, 2)],
            "not_classified": [res(1, 1, classification="DNF"), res(13, 2)],
        }
        self.assertEqual(order(riders), ["steady", "crashed_p2", "not_classified"])

    def test_final_pos_overrides_position(self):
        riders = {
            "penalised": [res(1, 1, final_pos=3)],
            "clean_second": [res(2, 1)],
        }
        self.assertEqual(order(riders), ["clean_second", "penalised"])


    def test_missing_round_and_no_results_do_not_crash(self):
        no_round = res(5, 1)
        no_round["attributes"]["race"]["data"]["attributes"]["grandPrix"] = None
        self.assertEqual(gp_tie_break_key([no_round])[1], 0)
        self.assertEqual(gp_tie_break_key([]), (tuple([0] * 30), 0))


def run_stats(all_results, standings):
    """standings: list of (standings_id, current_position, primary_grid_id, extra_grid_ids or None)."""
    from cron.stats_calc.moto_gp.moto_gp_stats_update_utils import update_moto_gp_stats

    driver_standings = []
    for sid, position, grid, extra in standings:
        attrs = {"position": position, "seasonGrid": {"data": {"id": grid}}}
        if extra:
            attrs["grids"] = {"data": [{"id": g} for g in extra]}
        driver_standings.append({"id": sid, "attributes": attrs})
    with mock.patch("cron.stats_calc.moto_gp.moto_gp_stats_update_utils.update_driver_standings") as upd, \
            mock.patch("cron.stats_calc.moto_gp.moto_gp_stats_update_utils.update_team_standings"):
        update_moto_gp_stats("2026", all_results, driver_standings, [])
    return {call.kwargs["row_id"]: call.kwargs["driver_map"]["position"] for call in upd.call_args_list}


class UpdateStatsOrderingTest(unittest.TestCase):
    def test_standings_positions_follow_regulations(self):
        all_results = (
            [res(10, 1, grid=1, points=6)]
            + [res(14, 1, rtype="Sprint", grid=2)]
            + [res(16, 1, grid=3), res(16, 2, grid=3)]
            + [res(16, 1, grid=4)]
            + [res(19, 1, grid=5)]
        )
        # Current order puts the Sprint-only rider (grid 2) ahead of the riders with Grand Prix finishes.
        standings = [(101, 1, 1, None), (102, 2, 2, None), (103, 3, 3, None), (104, 4, 4, None), (105, 5, 5, None)]
        self.assertEqual(run_stats(all_results, standings), {101: 1, 103: 2, 104: 3, 105: 4, 102: 5})

    def test_multi_grid_driver_results_are_merged_for_the_countback(self):
        # Rider 201 raced for two teams (grids 10 and 11): one 16th place on each. Rider 202 has a single 16th.
        all_results = [res(16, 1, grid=10), res(16, 2, grid=11), res(16, 1, grid=12)]
        standings = [(202, 1, 12, None), (201, 2, 10, [10, 11])]
        self.assertEqual(run_stats(all_results, standings), {201: 1, 202: 2})

    def test_rider_without_any_result_is_ranked_last_and_stable(self):
        all_results = [res(18, 1, grid=1)]
        standings = [(301, 1, 2, None), (302, 2, 1, None)]
        self.assertEqual(run_stats(all_results, standings), {302: 1, 301: 2})

    def test_fully_equal_riders_keep_their_current_order(self):
        all_results = [res(16, 1, grid=1), res(16, 1, grid=2)]
        standings = [(401, 2, 1, None), (402, 1, 2, None)]
        self.assertEqual(run_stats(all_results, standings), {402: 1, 401: 2})

    def test_points_always_beat_the_tie_break(self):
        all_results = [res(1, 1, grid=1), res(15, 1, grid=2, points=1)]
        standings = [(501, 1, 1, None), (502, 2, 2, None)]
        self.assertEqual(run_stats(all_results, standings), {502: 1, 501: 2})


if __name__ == "__main__":
    unittest.main()
