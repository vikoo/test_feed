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
    def mark(self, keys, when):
        if self.fail_mark: raise ConnectionError("github down")
        keys = [keys] if isinstance(keys, (str, int)) else list(keys)
        for k in keys: self.sent[str(k)] = when.isoformat()
        self.marked.append(keys[0])


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
        self.assertEqual(a["en"], ("🎯 Portugal GP: Qualifying", "Pole fight is about to start ⏱️🔥"))
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
        self.assertEqual(len([m for m in logged if "app shows" in str(m)]), 1)  # logged once
        self.assertEqual(problems, [])  # a same-day difference does not turn the run red

    def test_official_feed_down_falls_back_to_strapi_time(self):
        rem._official_cache.clear()
        def boom(sid): raise ConnectionError("down")
        now = FP1 - timedelta(hours=1)
        self.assertEqual(rem.official_starts("x", now, fetch=boom), {})
        r = race(600, "FP1", FP1); r["attributes"]["grandPrix"]["data"]["attributes"]["siteEventId"] = "x"
        self.assertEqual(rem.effective_start(r, now, lambda sid, n: rem.official_starts(sid, n, fetch=boom)), FP1)

    def test_session_cancelled_in_official_timetable_gets_no_reminder(self):
        r = race(592, "Race", FP1, name="AUSTRALIA GP 26")
        cancelled = lambda race_, now: "CANCELLED"
        self.assertEqual(rem.due([r], FP1 - timedelta(minutes=10), set(), lambda sid, n: {}, cancelled), [])
        self.assertEqual(len(rem.due([r], FP1 - timedelta(minutes=10), set(), lambda sid, n: {}, lambda race_, now: "NOT-STARTED")), 1)

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
        probs = rem.run_pass(FP1 - timedelta(minutes=5), lambda a, b: [race(i, k, FP1) for i, k in enumerate(("FP1", "Sprint", "Race"))], Store(), sent.append, True)
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
        with mock.patch.object(rem.requests, "get", side_effect=get), mock.patch.object(rem.requests, "put", side_effect=put), \
             mock.patch.object(rem.time, "sleep"):
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


class DuplicateAndControlTest(unittest.TestCase):
    def setUp(self):
        logger.remove()

    def test_duplicated_race_row_sends_one_push(self):
        a, b = race(606, "Race", FP1), race(700, "Race", FP1)
        st, sent = Store(), []
        for minute in (14, 12, 10):
            rem.run_pass(FP1 - timedelta(minutes=minute), lambda x, y: [a, b], st, sent.append, True,
                         official=lambda sid, now: {})
        self.assertEqual(len(sent), 1)

    def test_duplicated_gp_with_same_official_event_sends_one_push(self):
        a, b = race(606, "Race", FP1), race(700, "Race", FP1)
        b["attributes"]["grandPrix"] = {"data": {"id": "99", "attributes": {"name": "PORTUGAL GP 26", "siteEventId": "por"}}}
        a["attributes"]["grandPrix"]["data"]["attributes"]["siteEventId"] = "por"
        st, sent = Store(), []
        rem.run_pass(FP1 - timedelta(minutes=10), lambda x, y: [a, b], st, sent.append, True, official=lambda sid, now: {})
        rem.run_pass(FP1 - timedelta(minutes=8), lambda x, y: [b], st, sent.append, True, official=lambda sid, now: {})
        self.assertEqual(len(sent), 1)

    def test_two_different_sessions_due_at_once_send_nothing(self):
        st, sent = Store(), []
        p = rem.run_pass(FP1 - timedelta(minutes=10), lambda x, y: [race(600, "FP1", FP1), race(605, "Sprint", FP1)],
                         st, sent.append, True, official=lambda sid, now: {})
        self.assertEqual(sent, []); self.assertTrue(p)

    def test_skip_race_ids_as_string_or_number(self):
        for raw in ("600", 600, ["600"], [600]):
            st = Store(); st.remote = True
            st.control = lambda raw=raw: {"skip_race_ids": raw}
            sent = []
            rem.run_pass(FP1 - timedelta(minutes=10), lambda x, y: [race(600, "FP1", FP1)], st, sent.append, True,
                         official=lambda sid, now: {})
            self.assertEqual(sent, [], raw)


class CancelledStatusCacheTest(unittest.TestCase):
    def setUp(self):
        logger.remove()
        rem._status_cache.clear()

    def test_cancelled_status_seen_earlier_survives_a_feed_outage(self):
        r = race(606, "Race", FP1)
        r["attributes"]["grandPrix"]["data"]["attributes"]["siteEventId"] = "por"
        ok = lambda sid: {"Race": {"start": FP1, "status": "CANCELLED"}}
        def boom(sid): raise ConnectionError("down")
        self.assertEqual(rem.official_status(r, FP1 - timedelta(minutes=40), fetch=ok), "CANCELLED")  # runner warm-up
        self.assertEqual(rem.official_status(r, FP1 - timedelta(minutes=10), fetch=boom), "CANCELLED")  # outage
        st, sent = Store(), []
        with mock.patch.object(rem.requests, "get", side_effect=ConnectionError("down")):  # feed down at send time
            rem.run_pass(FP1 - timedelta(minutes=10), lambda a, b: [r], st, sent.append, True,
                         official=lambda sid, now: {})
        self.assertEqual(sent, [])


class LastMomentChangeTest(unittest.TestCase):
    """Ankur: check the latest schedule before every push and move the push if MotoGP changed it."""
    def setUp(self):
        logger.remove()
        rem._official_cache.clear(); rem._status_cache.clear()

    def _race(self):
        r = race(600, "FP1", FP1)
        r["attributes"]["grandPrix"]["data"]["attributes"]["siteEventId"] = "por"
        return r

    def test_session_moved_later_at_the_last_moment_moves_the_push(self):
        moved = FP1 + timedelta(minutes=30)
        calls = []
        def feed(sid):
            calls.append(1)
            return {"FP1": {"start": moved, "status": "NOT-STARTED"}}
        with mock.patch.object(rem, "fetch_official_sessions", side_effect=feed):
            r, st, sent = self._race(), Store(), []
            rem._official_cache["por"] = (FP1 - timedelta(minutes=20), {"FP1": FP1})
            rem._status_cache["por"] = (FP1 - timedelta(minutes=20), {"FP1": {"start": FP1, "status": "NOT-STARTED"}})
            orig = rem.refresh_official
            with mock.patch.object(rem, "refresh_official", side_effect=lambda sid, now: orig(sid, now, fetch=feed)):
                t = FP1 - timedelta(minutes=15)
                while t < moved:
                    rem.run_pass(t, lambda a, b: [r], st, lambda m, t=t: sent.append(t), True)
                    t += timedelta(minutes=1)
        self.assertEqual(sent, [moved - timedelta(minutes=15)])  # not at the old time, at the new one

    def test_session_cancelled_at_the_last_moment_sends_nothing(self):
        r, st, sent = self._race(), Store(), []
        rem._official_cache["por"] = (FP1 - timedelta(minutes=20), {"FP1": FP1})
        rem._status_cache["por"] = (FP1 - timedelta(minutes=20), {"FP1": {"start": FP1, "status": "NOT-STARTED"}})
        feed = lambda sid: {"FP1": {"start": FP1, "status": "CANCELLED"}}
        orig = rem.refresh_official
        with mock.patch.object(rem, "refresh_official", side_effect=lambda sid, now: orig(sid, now, fetch=feed)):
            rem.run_pass(FP1 - timedelta(minutes=14), lambda a, b: [r], st, sent.append, True)
        self.assertEqual(sent, [])

    def test_feed_down_at_send_time_uses_the_last_copy(self):
        r, st, sent = self._race(), Store(), []
        rem._official_cache["por"] = (FP1 - timedelta(minutes=20), {"FP1": FP1})
        rem._status_cache["por"] = (FP1 - timedelta(minutes=20), {"FP1": {"start": FP1, "status": "NOT-STARTED"}})
        def down(sid): raise ConnectionError("down")
        orig = rem.refresh_official
        with mock.patch.object(rem, "refresh_official", side_effect=lambda sid, now: orig(sid, now, fetch=down)), \
             mock.patch.object(rem.requests, "get", side_effect=ConnectionError("down")):
            rem.run_pass(FP1 - timedelta(minutes=14), lambda a, b: [r], st, sent.append, True)
        self.assertEqual(len(sent), 1)



class ResultsCopyTest(unittest.TestCase):
    def setUp(self):
        logger.remove()

    def _gp(self, name="PORTUGAL GP 26"):
        return {"id": "63", "attributes": {"name": name}}

    def test_every_language_and_every_2026_gp_passes_the_checks(self):
        self.assertEqual(set(rem.RESULT_TEMPLATES), {"en", *locales})
        for lang, sessions in rem.RESULT_TEMPLATES.items():
            self.assertEqual(set(sessions), set(rem.RESULT_TYPES), lang)
        for name in GP_NAMES_2026:
            for rtype in rem.RESULT_TYPES:
                self.assertEqual(set(rem.build_result_messages(self._gp(name), rtype)), {"en", *locales})

    def test_approved_english_copy(self):
        got = {t: rem.build_result_messages(self._gp(), t)["en"] for t in rem.RESULT_TYPES}
        self.assertEqual(got, {"FP1": ("📊 Portugal GP: FP1 results", "See who topped FP1 👀🔥"),
                               "PRACTICE": ("📊 Portugal GP: Practice", "Results are in: who made Q2? 🏁👀"),
                               "FP2": ("📊 Portugal GP: FP2 results", "See who topped FP2 👀🔥"),
                               "QNR2": ("🏁 Portugal GP: Grid is set", "See who took pole 👀🔥"),
                               "Sprint": ("⚡ Portugal GP: Sprint results", "See who won the Sprint 🏆🔥"),
                               "Race": ("🏆 Portugal GP: Race results", "See who won the Race 🏆🔥")})

    def test_no_results_push_after_q1(self):
        with self.assertRaises(ValueError):
            rem.build_result_messages(self._gp(), "QNR1")

    def test_uploader_sends_the_fixed_copy_without_translation(self):
        from cron.data_upload.moto_gp import moto_gp_data_upload as up
        with mock.patch.object(up, "send_localized_notification_to_topic") as send:
            up.send_results_push("Race", self._gp())
        messages = send.call_args.kwargs["messages"]
        self.assertEqual(messages["en"], ("🏆 Portugal GP: Race results", "See who won the Race 🏆🔥"))
        self.assertEqual(messages["it"], ("🏆 Portugal GP: risultati gara", "Scopri chi ha vinto la gara 🏆🔥"))
        self.assertEqual(len(messages), 10)


class CopyEarlyWarningTest(unittest.TestCase):
    def test_every_2026_gp_name_is_clean(self):
        for name in GP_NAMES_2026:
            self.assertEqual(rem.copy_problems(name), [], name)

    def test_a_longer_future_name_is_flagged(self):
        bad = rem.copy_problems("EMILIA ROMAGNA AND RIMINI COAST GP 27")
        self.assertTrue(bad); self.assertTrue(all(" en:" in b or " " in b for b in bad))

