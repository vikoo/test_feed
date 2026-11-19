import json
import unittest
from datetime import datetime, timedelta, timezone

from loguru import logger

from cron.data_upload.moto_gp import time_sync as ts

UTC = timezone.utc
# Qatar 2026 as Strapi had it before the fix (backup_qatar_times_1794071456.json) and the official timetable
STRAPI_OLD = {"481": ("FP1", "2026-11-06T12:45:00.000Z"), "482": ("PRACTICE", "2026-11-06T17:00:00.000Z"),
              "483": ("FP2", "2026-11-07T12:00:00.000Z"), "484": ("QNR1", "2026-11-07T12:40:00.000Z"),
              "485": ("QNR2", "2026-11-07T13:05:00.000Z"), "486": ("Sprint", "2026-11-07T17:00:00.000Z"),
              "487": ("Race", "2026-11-08T17:00:00.000Z")}
OFFICIAL = {t: datetime.fromisoformat(v.replace("Z", "+00:00")) - timedelta(hours=1) for t, v in STRAPI_OLD.values()}


def races(start_date="2026-11-06T12:45:00.000Z", end_date="2026-11-08T17:45:00.000Z"):
    gp = {"id": "46", "attributes": {"siteEventId": "qat", "isCancelled": None, "startDate": start_date, "endDate": end_date}}
    return [{"id": rid, "attributes": {"type": t, "startTime": st, "siteEventId": "x", "grandPrix": {"data": gp}}}
            for rid, (t, st) in STRAPI_OLD.items()]


class TimeSyncTest(unittest.TestCase):
    def setUp(self):
        logger.remove()

    def test_qatar_two_days_out_fixes_every_session_and_the_gp_window(self):
        now = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
        changes, gp = ts.plan(races(), lambda sid: OFFICIAL, now)
        self.assertEqual(len(changes), 7)
        self.assertTrue(all(new == old - timedelta(hours=1) for _, old, new in changes))
        self.assertEqual(gp["46"], {"startDate": "2026-11-06T11:45:00.000Z", "endDate": "2026-11-08T16:45:00.000Z"})

    def test_broken_end_date_before_the_race_is_repaired(self):
        # the real pre-fix Qatar endDate was 08 Nov 05:45 UTC, before the Race
        _, gp = ts.plan(races(end_date="2026-11-08T05:45:00.000Z"), lambda sid: OFFICIAL, datetime(2026, 11, 4, tzinfo=UTC))
        self.assertEqual(gp["46"]["endDate"], "2026-11-08T16:45:00.000Z")

    def test_same_day_delay_is_left_as_planned(self):
        now = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)  # FP1 and Practice are within 6 h... FP1 is
        changes, _ = ts.plan(races(), lambda sid: OFFICIAL, now)
        self.assertNotIn("FP1", [r["attributes"]["type"] for r, _, _ in changes])

    def test_matching_times_change_nothing(self):
        same = {t: datetime.fromisoformat(v.replace("Z", "+00:00")) for t, v in STRAPI_OLD.values()}
        self.assertEqual(ts.plan(races(), lambda sid: same, datetime(2026, 11, 4, tzinfo=UTC)), ([], {}))

    def test_official_feed_without_a_session_changes_nothing(self):
        self.assertEqual(ts.plan(races(), lambda sid: {}, datetime(2026, 11, 4, tzinfo=UTC)), ([], {}))

    def test_move_of_more_than_two_days_is_held(self):
        far = {t: v + timedelta(days=7) for t, v in OFFICIAL.items()}  # wrong event linked
        held = []
        changes, gp = ts.plan(races(), lambda sid: far, datetime(2026, 11, 4, tzinfo=UTC), held)
        self.assertEqual((changes, gp), ([], {})); self.assertEqual(len(held), 7)

    def test_make_pass_writes_only_the_time_and_skips_cancelled(self):
        from unittest import mock
        import cron.strapi_api.apis as apis
        import cron.notifiaction.moto_gp_session_reminders as rem
        sessions = {t: {"start": v, "status": "CANCELLED" if t == "Race" else "NOT-STARTED"} for t, v in OFFICIAL.items()}
        puts = []
        def put(url, json=None, **kw):
            puts.append((url.rsplit("/api/", 1)[1], json["data"]))
            return mock.Mock(raise_for_status=lambda: None)
        with mock.patch.object(apis, "get_races_starting_between", return_value=races()), \
             mock.patch.object(apis, "update_config_for_gp") as bump, \
             mock.patch.object(rem, "fetch_official_sessions", side_effect=lambda sid: sessions), \
             mock.patch("requests.put", side_effect=put):
            problems = ts.make_pass()(datetime(2026, 11, 4, 12, 0, tzinfo=UTC))
        self.assertEqual(problems, [])
        race_puts = [p for p in puts if p[0].startswith("races/")]
        self.assertEqual(len(race_puts), 6)  # the cancelled Race is not moved
        self.assertTrue(all(set(d) == {"startTime"} for _, d in race_puts))
        self.assertNotIn("487", [p[0].split("/")[1] for p in race_puts])
        self.assertEqual(bump.call_count, 1)


if __name__ == "__main__":
    unittest.main()
