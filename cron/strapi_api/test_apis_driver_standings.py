import unittest
from unittest import mock

from cron.strapi_api import apis, api_queries


def response(payload):
    r = mock.Mock()
    r.json.return_value = payload
    r.raise_for_status.return_value = None
    return r


class NoCacheTest(unittest.TestCase):
    def test_wraps_query_with_a_unique_leading_comment(self):
        a, b = apis.no_cache("{ a }"), apis.no_cache("{ a }")
        self.assertTrue(a.startswith("# "))
        self.assertTrue(a.endswith("\n{ a }"))
        self.assertNotEqual(a, b)


class ReadsBypassTheProxyCacheTest(unittest.TestCase):
    def sent_query(self, fn, payload, *args, **kwargs):
        with mock.patch.object(apis.requests, "post", return_value=response(payload)) as post:
            fn(*args, **kwargs)
        return post.call_args.kwargs["json"]["query"]

    def test_stats_job_reads_are_cache_busted(self):
        q = self.sent_query(apis.fetch_driver_team_standings_for_season, {"data": {}}, False, "2026")
        self.assertTrue(q.startswith("# ") and q.endswith(api_queries.query_driver_and_team_standings))
        q = self.sent_query(apis.fetch_all_race_results, {"data": {"raceResults": {"data": []}}}, False, "2026")
        self.assertTrue(q.startswith("# ") and q.endswith(api_queries.query_race_results_all))
        q = self.sent_query(apis.get_active_season_grids_by_number, {"data": {}}, False, "2026")
        self.assertTrue(q.startswith("# ") and q.endswith(api_queries.query_season_grid))
        q = self.sent_query(apis.driver_standing_exists_for_grid, {"data": {"byPrimaryGrid": {"data": []}, "byExtraGrid": {"data": []}}}, False, 90)
        self.assertTrue(q.startswith("# ") and q.endswith(api_queries.query_driver_standings_for_season_grid))


class GridsByNumberTest(unittest.TestCase):
    def test_groups_all_active_grids_and_skips_old_ones(self):
        grids = [
            {"id": "86", "attributes": {"driverNumber": 51, "isOldGrid": None}},
            {"id": "90", "attributes": {"driverNumber": 51, "isOldGrid": None}},
            {"id": "57", "attributes": {"driverNumber": 30, "isOldGrid": True}},
            {"id": "94", "attributes": {"driverNumber": 30, "isOldGrid": None}},
            {"id": "99", "attributes": {"driverNumber": None}},
        ]
        with mock.patch.object(apis.requests, "post", return_value=response({"data": {"seasonGrids": {"data": grids}}})):
            self.assertEqual(apis.get_active_season_grids_by_number(False, "2026"), {51: ["86", "90"], 30: ["94"]})


class ExistsTest(unittest.TestCase):
    def exists(self, primary, extra):
        payload = {"data": {"byPrimaryGrid": {"data": primary}, "byExtraGrid": {"data": extra}}}
        with mock.patch.object(apis.requests, "post", return_value=response(payload)):
            return apis.driver_standing_exists_for_grid(False, 90)

    def test_found_by_primary_grid(self):
        self.assertTrue(self.exists([{"id": "1"}], []))

    def test_found_by_extra_grid(self):
        self.assertTrue(self.exists([], [{"id": "1"}]))

    def test_not_found(self):
        self.assertFalse(self.exists([], []))

    def test_graphql_errors_raise_instead_of_reporting_missing(self):
        with mock.patch.object(apis.requests, "post", return_value=response({"errors": [{"message": "x"}]})):
            with self.assertRaises(RuntimeError):
                apis.driver_standing_exists_for_grid(False, 90)


class CreateTest(unittest.TestCase):
    def test_sends_published_row_and_returns_id(self):
        payload = {"data": {"createDriverStanding": {"data": {"id": "96"}}}}
        with mock.patch.object(apis.requests, "post", return_value=response(payload)) as post:
            self.assertEqual(apis.create_driver_standing(False, 6, 95, 32), "96")
        sent = post.call_args.kwargs["json"]
        self.assertEqual(sent["query"], api_queries.mutation_create_driver_standing)
        data = sent["variables"]["input"]
        self.assertEqual((data["season"], data["seasonGrid"], data["position"], data["points"]), ("6", "95", 32, 0))
        self.assertRegex(data["publishedAt"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.000Z$")

    def test_missing_id_raises(self):
        with mock.patch.object(apis.requests, "post", return_value=response({"errors": [{"message": "invalid"}]})):
            with self.assertRaises(RuntimeError):
                apis.create_driver_standing(False, 6, 95, 32)


if __name__ == "__main__":
    unittest.main()
