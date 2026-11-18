import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from loguru import logger

from cron.notifiaction import moto_gp_session_reminders as rem
from cron.notifiaction.notification_message_utils import get_title_body_for_notification
from cron.utils import locales

FP1 = datetime(2026, 11, 20, 10, 45, tzinfo=timezone.utc)
GP_NAMES_2026 = ["THAILAND GP 26", "BRAZIL GP 26", "USA GP 26", "SPAIN GP 26", "FRANCE  GP 26", "CATALONIA GP 26",
                 "ITALY GP 26", "HUNGARY GP 26", "CZECHIA GP 26", "NETHERLANDS GP 26", "GERMANY  GP 26",
                 "GREAT BRITAIN GP 26", "ARAGON GP 26", "SAN MARINO GP 26", "AUSTRIA GP 26", "JAPAN GP 26",
                 "INDONESIA GP 26", "AUSTRALIA GP 26", "MALAYSIA GP 26", "QATAR GP 26", "PORTUGAL GP 26",
                 "VALENCIA GP 26"]


def race(rid, rtype, start, cancelled=None, name="PORTUGAL GP 26"):
    return {"id": str(rid), "attributes": {"type": rtype, "startTime": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "grandPrix": {"data": {"id": "47", "attributes": {"name": name, "isCancelled": cancelled}}}}}


class Store(rem.SentStore):
    def __init__(self, fail_load=False, fail_mark=False):
        super().__init__(token="", repo="")
        self.fail_load, self.fail_mark, self.marked = fail_load, fail_mark, []
    def load(self):
        if self.fail_load: raise ConnectionError("github down")
        return self.sent
    def mark(self, race_id, when):
        if self.fail_mark: raise ConnectionError("github down")
        self.sent[str(race_id)] = when.isoformat(); self.marked.append(race_id)


class RemindersTest(unittest.TestCase):
    def setUp(self):
        logger.remove()

    def test_every_language_and_every_2026_gp_passes_the_checks(self):
        self.assertEqual(set(rem.TEMPLATES), {"en", *locales})
        for lang, sessions in rem.TEMPLATES.items():
            self.assertEqual(set(sessions), set(rem.REMIND_TYPES), lang)
        for name in GP_NAMES_2026:
            for rtype in rem.REMIND_TYPES:
                msgs = rem.build_messages(race(1, rtype, FP1, name=name))
                self.assertEqual(set(msgs), {"en", *locales})

    def test_copy_is_the_same_every_weekend_except_the_gp_name(self):
        a = rem.build_messages(race(1, "QNR1", FP1, name="PORTUGAL GP 26"))
        b = rem.build_messages(race(2, "QNR1", FP1, name="VALENCIA GP 26"))
        self.assertEqual(a["en"], ("🎯 Portugal GP: Qualifying", "Pole fight starts now ⏱️🔥"))
        for lang in a:
            self.assertEqual(a[lang][1], b[lang][1])
            self.assertEqual(a[lang][0].replace("Portugal", "Valencia"), b[lang][0])

    def test_gp_display_name(self):
        self.assertEqual(rem.gp_display_name("GERMANY  GP 26"), "Germany GP")
        self.assertEqual(rem.gp_display_name("USA GP 26"), "USA GP")
        self.assertEqual(rem.gp_display_name("GREAT BRITAIN GP 26"), "Great Britain GP")

    def test_a_line_that_fails_the_checks_is_not_sent(self):
        with self.assertRaises(ValueError):
            rem.build_messages(race(1, "QNR1", FP1, name="AN EXTREMELY LONG GRAND PRIX NAME GP 26"))

    def test_due_window_and_session_rules(self):
        now = FP1 - timedelta(minutes=15)
        races = [race(600, "FP1", FP1), race(603, "QNR1", FP1 - timedelta(minutes=5)),
                 race(604, "QNR2", FP1 - timedelta(minutes=10)), race(9, "FP1", FP1, cancelled=True),
                 race(605, "Sprint", FP1 + timedelta(minutes=10))]
        self.assertEqual([r["id"] for r in rem.due(races, now, set())], ["600", "603"])
        self.assertEqual(rem.due(races, now, {"600", "603"}), [])
        self.assertEqual(rem.due([race(600, "FP1", FP1)], FP1, set()), [])
        self.assertEqual(rem.due([race(600, "FP1", FP1)], FP1 - timedelta(minutes=16), set()), [])

    def test_qatar_case_official_time_wins_and_wrong_app_time_is_reported(self):
        strapi_fp1 = datetime(2026, 11, 6, 12, 45, tzinfo=timezone.utc)   # what Strapi had
        official_fp1 = datetime(2026, 11, 6, 11, 45, tzinfo=timezone.utc)  # motogp.com
        r = race(481, "FP1", strapi_fp1, name="QATAR GP 26")
        r["attributes"]["grandPrix"]["data"]["attributes"]["siteEventId"] = "qat"
        official = lambda sid, now: {"FP1": official_fp1} if sid == "qat" else {}
        sent, st, problems, logged = [], Store(), [], set()
        t = official_fp1 - timedelta(minutes=30)
        while t < strapi_fp1:
            problems += rem.run_pass(t, lambda a, b: [r], st, lambda m: sent.append(t), True, logged, official)
            t += timedelta(minutes=1)
        self.assertEqual(sent, [official_fp1 - timedelta(minutes=15)])
        self.assertEqual(len([p for p in problems if "app shows" in p]), 1)

    def test_official_feed_down_falls_back_to_strapi_time(self):
        rem._official_cache.clear()
        def boom(sid): raise ConnectionError("down")
        now = FP1 - timedelta(hours=1)
        self.assertEqual(rem.official_starts("x", now, fetch=boom), {})
        r = race(600, "FP1", FP1); r["attributes"]["grandPrix"]["data"]["attributes"]["siteEventId"] = "x"
        self.assertEqual(rem.effective_start(r, now, lambda sid, n: rem.official_starts(sid, n, fetch=boom)), FP1)

    def test_dry_run_sends_nothing(self):
        sent, st = [], Store()
        probs = rem.run_pass(FP1 - timedelta(minutes=14), lambda a, b: [race(600, "FP1", FP1)], st, sent.append, False)
        self.assertEqual((sent, probs, st.marked), ([], [], []))

    def test_sends_once_and_records(self):
        sent, st = [], Store()
        for minute in (15, 13, 11):
            rem.run_pass(FP1 - timedelta(minutes=minute), lambda a, b: [race(600, "FP1", FP1)], st, sent.append, True)
        self.assertEqual(len(sent), 1); self.assertEqual(st.marked, ["600"])

    def test_no_record_means_no_send(self):
        sent = []
        probs = rem.run_pass(FP1 - timedelta(minutes=14), lambda a, b: [race(600, "FP1", FP1)], Store(fail_load=True), sent.append, True)
        self.assertEqual(sent, []); self.assertTrue(probs)

    def test_too_many_due_sends_nothing(self):
        sent = []
        probs = rem.run_pass(FP1 - timedelta(minutes=5), lambda a, b: [race(i, "FP1", FP1) for i in range(3)], Store(), sent.append, True)
        self.assertEqual(sent, []); self.assertTrue(probs)

    def test_results_push_uses_plain_session_names(self):
        gp = race(1, "Race", FP1)["attributes"]["grandPrix"]["data"]
        gp["attributes"]["track"] = {"data": {"attributes": {"name": "Algarve", "country": "Portugal"}}}
        self.assertEqual(get_title_body_for_notification(gp, "QNR2")[0], "PORTUGAL GP: Qualifying Results Out!")
        self.assertEqual(get_title_body_for_notification(gp, "PRACTICE")[0], "PORTUGAL GP: Practice Results Out!")


if __name__ == "__main__":
    unittest.main()


class HardeningTest(unittest.TestCase):
    def setUp(self):
        logger.remove()

    def _remote_store(self, put_status=500, control=None):
        st = rem.SentStore(token="t", repo="o/r")
        def get(url, **kw):
            m = mock.Mock()
            if url.endswith(rem.CONTROL_PATH):
                m.status_code = 200 if control is not None else 404
                m.json = lambda: {"sha": "c", "content": rem.base64.b64encode(rem.json.dumps(control or {}).encode()).decode()}
            elif "git/ref" in url:
                m.status_code = 200; m.json = lambda: {"object": {"sha": "m"}}
            else:
                m.status_code = 404  # remote record never gets the id: every write fails
            m.raise_for_status = lambda: None
            return m
        def put(url, **kw):
            m = mock.Mock(); m.status_code = put_status
            def boom():
                raise rem.requests.HTTPError("500")
            m.raise_for_status = boom if put_status >= 400 else (lambda: None)
            m.json = lambda: {"content": {"sha": "s"}}
            return m
        return st, get, put

    def test_failed_record_write_never_resends(self):
        st, get, put = self._remote_store(put_status=500)
        sent = []
        with mock.patch.object(rem.requests, "get", side_effect=get), mock.patch.object(rem.requests, "put", side_effect=put):
            for minute in (15, 13, 11, 9, 7, 5, 3, 1):
                rem.run_pass(FP1 - timedelta(minutes=minute), lambda a, b: [race(600, "FP1", FP1)], st, sent.append, True)
        self.assertEqual(len(sent), 1)

    def test_control_file_pauses_and_skips(self):
        for control, expect in (({"session_push": "off"}, 0), ({"skip_race_ids": ["600"]}, 0), ({}, 1)):
            st, get, put = self._remote_store(put_status=201, control=control)
            sent = []
            with mock.patch.object(rem.requests, "get", side_effect=get), mock.patch.object(rem.requests, "put", side_effect=put):
                rem.run_pass(FP1 - timedelta(minutes=10), lambda a, b: [race(600, "FP1", FP1)], st, sent.append, True)
            self.assertEqual(len(sent), expect, control)

    def test_one_failing_locale_is_dropped_not_the_whole_push(self):
        with mock.patch.dict(rem.TEMPLATES["fr"], {"FP1": ("🏍️ {gp} : un titre beaucoup trop long pour passer", "x 🔥")}):
            msgs = rem.build_messages(race(1, "FP1", FP1))
        self.assertNotIn("fr", msgs); self.assertIn("en", msgs); self.assertEqual(len(msgs), 9)
