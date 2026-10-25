"""Grid stats, poles, GP count and classified finishes of the MotoGP stats job.

Run: python3 -m unittest discover -s cron -t . -p "test_*.py"
"""
import unittest
from unittest import mock

from cron.stats_calc.moto_gp.moto_gp_stats_update_utils import populate_moto_gp_driver_data, update_moto_gp_stats

_ids = iter(range(1, 100000))


def row(rtype, gp, pos, *, rider=1, grid=10, final=None, sprint_final=None, points=0, dnf=False, laps=10, time="1:30.000"):
    return {"id": str(next(_ids)), "attributes": {
        "race": {"data": {"attributes": {"type": rtype, "grandPrix": {"data": {"id": str(gp), "attributes": {"round": str(gp)}}}}}},
        "seasonGrid": {"data": {"id": str(grid), "attributes": {"driver": {"data": {"id": str(rider)}}}}},
        "position": pos, "finalPos": final, "sprintFinalPos": sprint_final, "points": points, "dnf": dnf,
        "laps": laps, "time": time, "fastestLap": False, "classification": {"data": None}}}


def stats(rows):
    return populate_moto_gp_driver_data("1", "10", rows, 1)


class GridStatsTest(unittest.TestCase):
    def test_cancelled_race_is_not_a_start(self):
        # Australia 2026: pole in Q2, Sprint run, Race cancelled (no Race rows)
        m = stats([row("QNR2", 1, 1), row("Sprint", 1, 1, points=12)])
        self.assertEqual(m["racePoles"], 1)
        self.assertEqual(m["raceFirstRowStarts"], 0)
        self.assertEqual(m["avgRaceStartGridPosition"], -999)
        self.assertEqual(m["avgRacePositionGained"], -999)
        self.assertEqual(m["sprintFirstRowStarts"], 1)
        self.assertEqual(m["avgSprintStartGridPosition"], 1)
        self.assertEqual(m["noOfGPs"], 1)

    def test_pole_stays_with_qualifying_when_grid_penalty(self):
        # Q2 P1, three-place Race grid penalty (finalPos 4), Sprint from pole (sprintFinalPos 1)
        m = stats([row("QNR2", 1, 1, final=4, sprint_final=1), row("Race", 1, 2), row("Sprint", 1, 1)])
        self.assertEqual(m["racePoles"], 1)
        self.assertEqual(m["sprintPoles"], 1)
        self.assertEqual(m["raceFirstRowStarts"], 0)
        self.assertEqual(m["avgRaceStartGridPosition"], 4)
        self.assertEqual(m["avgRacePositionGained"], 2)
        self.assertEqual(m["sprintFirstRowStarts"], 1)

    def test_non_starter_counts_only_the_session_started(self):
        # France 2026 #93: started the Sprint from P2, did not start the Race (no Race row, finalPos 22)
        m = stats([row("QNR2", 1, 2, final=22, sprint_final=2), row("Sprint", 1, 5)])
        self.assertEqual(m["raceFirstRowStarts"], 0)
        self.assertEqual(m["avgRaceStartGridPosition"], -999)
        self.assertEqual(m["sprintFirstRowStarts"], 1)
        self.assertEqual(m["avgSprintPositionGained"], -3)

    def test_q1_slot_without_final_pos_is_position_plus_ten(self):
        m = stats([row("QNR1", 1, 3), row("Race", 1, 9)])
        self.assertEqual(m["avgRaceStartGridPosition"], 13)
        self.assertEqual(m["raceFirstRowStarts"], 0)

    def test_q1_riders_promoted_to_q2_use_their_q2_row(self):
        m = stats([row("QNR1", 1, 1), row("QNR2", 1, 3), row("Race", 1, 3)])
        self.assertEqual(m["avgRaceStartGridPosition"], 3)
        self.assertEqual(m["raceFirstRowStarts"], 1)
        self.assertEqual(m["q3Appearances"], 1)

    def test_start_without_qualifying_row_is_not_a_grid_entry(self):
        m = stats([row("Race", 1, 15)])
        self.assertEqual(m["avgRaceStartGridPosition"], -999)
        self.assertEqual(m["avgRaceFinishPosition"], 15)

    def test_averages_over_several_starts(self):
        rows = [row("QNR2", 1, 2), row("Race", 1, 1), row("QNR2", 2, 6), row("Race", 2, 4, dnf=True)]
        m = stats(rows)
        self.assertEqual(m["avgRaceStartGridPosition"], 4)
        self.assertEqual(m["avgRacePositionGained"], 4 - 2.5)
        self.assertEqual(m["raceFirstRowStarts"], 1)

    def test_rider_on_two_grids_is_matched_by_driver(self):
        # wild card grid in Q, substitute grid in the Race of the same GP: the same rider
        m = stats([row("QNR2", 1, 5, grid=88), row("Race", 1, 7, grid=97)])
        self.assertEqual(m["avgRaceStartGridPosition"], 5)


class GpCountTest(unittest.TestCase):
    def test_practice_only_event_counts(self):
        # rode FP1 and withdrew: took part in the event (FIM Art. 1.11.9)
        m = stats([row("FP1", 1, 18), row("QNR2", 2, 4), row("Race", 2, 3)])
        self.assertEqual(m["noOfGPs"], 2)

    def test_entry_without_lap_or_time_does_not_count(self):
        m = stats([row("FP1", 1, 23, laps=0, time="", dnf=True), row("FP1", 2, 5)])
        self.assertEqual(m["noOfGPs"], 1)

    def test_time_without_laps_counts(self):
        m = stats([row("PRACTICE", 1, 20, laps=0, time="01:31.555")])
        self.assertEqual(m["noOfGPs"], 1)

    def test_dnf_placeholder_time_does_not_count(self):
        m = stats([row("PRACTICE", 1, 22, laps=0, time="DNF", dnf=True)])
        self.assertEqual(m["noOfGPs"], 0)

    def test_sprint_start_counts_even_with_zero_laps(self):
        m = stats([row("Sprint", 1, 22, laps=0, time="", dnf=True)])
        self.assertEqual(m["noOfGPs"], 1)


class ClassifiedFinishTest(unittest.TestCase):
    def test_dnf_row_is_not_a_win_podium_or_top_finish(self):
        # few finishers: a retired rider can carry position 3
        m = stats([row("Race", 1, 3, dnf=True), row("Race", 2, 1)])
        self.assertEqual(m["raceWins"], 1)
        self.assertEqual(m["racePodiums"], 1)
        self.assertEqual(m["top5FinishInRace"], 1)
        self.assertEqual(m["top10FinishInRace"], 1)
        self.assertEqual(m["dnfInRace"], 1)
        self.assertEqual(m["bestRaceFinish"], 1)
        self.assertEqual(m["avgRaceFinishPosition"], 2)

    def test_no_races_keeps_the_no_value_marker(self):
        m = stats([row("QNR2", 1, 8)])
        self.assertEqual(m["avgRaceFinishPosition"], -999)
        self.assertEqual(m["bestRaceFinish"], 0)
        self.assertEqual(m["avgPointsPerRace"], 0.0)


class TeamPoolingTest(unittest.TestCase):
    def test_team_grid_averages_pool_both_riders(self):
        rows = [row("QNR2", 1, 1, rider=1, grid=10), row("Race", 1, 2, rider=1, grid=10),
                row("QNR2", 1, 9, rider=2, grid=11), row("Race", 1, 5, rider=2, grid=11)]
        driver_standings = [
            {"id": "1", "attributes": {"position": 1, "seasonGrid": {"data": {"id": "10"}}, "grids": {"data": []}}},
            {"id": "2", "attributes": {"position": 2, "seasonGrid": {"data": {"id": "11"}}, "grids": {"data": []}}}]
        team_standings = [{"id": "7", "attributes": {"position": 1, "seasonGrid": {"data": [{"id": "10"}, {"id": "11"}]}}}]
        with mock.patch("cron.stats_calc.moto_gp.moto_gp_stats_update_utils.update_driver_standings"), \
                mock.patch("cron.stats_calc.moto_gp.moto_gp_stats_update_utils.update_team_standings"):
            _, teams = update_moto_gp_stats("2026", rows, driver_standings, team_standings)
        t = teams[0]
        self.assertEqual(t["avgRaceStartGridPosition"], 5)
        self.assertEqual(t["avgRacePositionGained"], 5 - 3.5)
        self.assertEqual(t["raceFirstRowStarts"], 1)
        self.assertEqual(t["racePoles"], 1)
        self.assertEqual(t["noOfGPs"], 1)


class FetchVariablesTest(unittest.TestCase):
    def _variables(self, **kwargs):
        from cron.strapi_api import apis
        sent = []

        class Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"data": {"raceResults": {"data": []}}}

        def fake_post(url, json=None, headers=None):
            sent.append(json["variables"])
            return Resp()

        with mock.patch.object(apis.requests, "post", side_effect=fake_post):
            apis.fetch_all_race_results(is_f1_feed=True, season="2026", **kwargs)
        return sent[0]

    def test_default_call_sends_the_original_variables(self):
        # F1 calls without overrides: the query defaults (old type list, no sort) apply
        self.assertEqual(self._variables(), {"season": "2026", "limit": 50, "start": 0})

    def test_overrides_are_sent(self):
        v = self._variables(session_types=["Race", "FP1"], sort=["id:asc"])
        self.assertEqual(v["types"], ["Race", "FP1"])
        self.assertEqual(v["sort"], ["id:asc"])


if __name__ == "__main__":
    unittest.main()
