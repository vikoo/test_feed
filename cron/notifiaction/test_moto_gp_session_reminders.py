import unittest
from datetime import datetime, timedelta, timezone

from loguru import logger

from cron.notifiaction import moto_gp_session_reminders as rem
from cron.notifiaction.notification_message_utils import get_title_body_for_notification
from cron.utils import locales

FP1 = datetime(2026, 11, 20, 10, 45, tzinfo=timezone.utc)


def race(rid, rtype, start, cancelled=None, city="Portimão", country="Portugal"):
    return {"id": str(rid), "attributes": {"type": rtype, "startTime": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "grandPrix": {"data": {"id": "47", "attributes": {"name": "PORTUGAL GP 26", "isCancelled": cancelled,
                          "track": {"data": {"attributes": {"city": city, "country": country}}}}}}}}


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

    def test_every_pool_line_passes_the_checks_with_real_names(self):
        cities = [("Portimão", "Portugal"), ("Sachsenring", "Germany"), ("Termas de Río Hondo", "Argentina"),
                  ("Mandalika", "Indonesia"), ("Valencia", "Spain")]
        names = ["M. Marquez", "F. Di Giannantonio", "R. Fernandez"]
        bad = []
        for lang, sessions in rem.POOLS.items():
            self.assertEqual(set(sessions), set(rem.REMIND_TYPES), lang)
            for rtype, pool in sessions.items():
                fact_free_bodies = [b for b in pool["bodies"] if "{leader}" not in b and "{pole}" not in b]
                self.assertTrue(fact_free_bodies, (lang, rtype))
                for city, country in cities:
                    v = {"flag": rem.flag(country), "city": city, "country": country}
                    for t in pool["titles"]:
                        title = t.format(**v)
                        if not rem.valid(title, "ok 🏁") and "{city}" not in t:
                            bad.append((lang, rtype, title))
                    for b in fact_free_bodies:
                        if not rem.valid("ok 🏁", b.format(**v)):
                            bad.append((lang, rtype, b))
        self.assertEqual(bad, [])
        for rtype in rem.REMIND_TYPES:
            for name in names:
                msgs = rem.build_messages(race(1, rtype, FP1), {"leader": name, "gap": 123, "pole": name})
                self.assertEqual(set(msgs), {"en", *locales})
                for lang, (title, body) in msgs.items():
                    self.assertTrue(rem.valid(title, body), (lang, rtype, title, body))

    def _gp_race(self, rtype, rnd, year=2026):
        r = race(1, rtype, FP1)
        a = r["attributes"]["grandPrix"]["data"]["attributes"]
        a["round"] = str(rnd); a["season"] = {"data": {"attributes": {"year": str(year)}}}
        return r

    def test_rotation_uses_every_pair_and_never_repeats_back_to_back(self):
        for rtype in rem.REMIND_TYPES:
            for lang in ("en", "it", "es"):
                seq = [rem.build_messages(self._gp_race(rtype, rnd))[lang] for rnd in range(1, 37)]
                v = {"flag": "🇵🇹", "city": "Portimão", "country": "Portugal"}
                nt = len([t for t in rem.POOLS[lang][rtype]["titles"] if rem.valid(rem._fill(t, v) or "{", "ok 🏁")])
                nb = len([b for b in rem.POOLS[lang][rtype]["bodies"] if rem.valid("ok 🏁", rem._fill(b, v) or "{")])
                if not (nb == 2 and nt % 2 == 0):
                    self.assertEqual(len(set(seq)), nt * nb, (rtype, lang))
                for a, b in zip(seq, seq[1:]):
                    self.assertNotEqual(a[0], b[0], (rtype, lang, "heading repeated next weekend"))
                    self.assertNotEqual(a[1], b[1], (rtype, lang, "body repeated next weekend"))

    def test_rotation_for_every_pool_size(self):
        for nt in range(1, 8):
            for nb in range(1, 8):
                seq = [rem.rotation(seed, nt, nb) for seed in range(46000, 46000 + nt * nb * 3)]
                for a, b in zip(seq, seq[1:]):
                    if nt > 1: self.assertNotEqual(a[0], b[0], (nt, nb))
                    if nb > 1: self.assertNotEqual(a[1], b[1], (nt, nb))
                if not (nb == 2 and nt % 2 == 0):
                    self.assertEqual(len(set(seq)), nt * nb, (nt, nb))

    def test_next_season_does_not_replay_this_season(self):
        same = sum(rem.build_messages(self._gp_race("QNR1", rnd, 2026))["en"] == rem.build_messages(self._gp_race("QNR1", rnd, 2027))["en"]
                   for rnd in range(1, 23))
        self.assertEqual(same, 0)

    def test_facts_only_in_their_sessions(self):
        facts = {"leader": "M. Marquez", "gap": 44, "pole": "J. Martin"}
        for rnd in range(1, 7):
            for rtype in ("FP2", "QNR1", "Race"):
                r = race(1, rtype, FP1); r["attributes"]["grandPrix"]["data"]["attributes"]["round"] = str(rnd)
                text = " ".join(" ".join(x) for x in rem.build_messages(r, facts).values())
                self.assertNotIn("Marquez", text, "no standings outside Friday")
                if rtype != "Race":
                    self.assertNotIn("Martin", text)

    def test_missing_fact_falls_back_to_a_fact_free_line(self):
        for rnd in range(1, 7):
            r = race(1, "Race", FP1); r["attributes"]["grandPrix"]["data"]["attributes"]["round"] = str(rnd)
            for title, body in rem.build_messages(r, {}).values():
                self.assertTrue(rem.valid(title, body))

    def test_short_name(self):
        self.assertEqual(rem.short_name("Marc Marquez"), "M. Marquez")
        self.assertEqual(rem.short_name("Fabio Di Giannantonio"), "F. Di Giannantonio")

    def test_flag_fallback(self):
        self.assertEqual(rem.flag("Spain"), "🇪🇸")
        self.assertEqual(rem.flag("Atlantis"), "🏁")

    def test_due_window_and_session_rules(self):
        now = FP1 - timedelta(minutes=15)
        races = [race(600, "FP1", FP1), race(603, "QNR1", FP1 - timedelta(minutes=5)),
                 race(604, "QNR2", FP1 - timedelta(minutes=10)), race(9, "FP1", FP1, cancelled=True),
                 race(605, "Sprint", FP1 + timedelta(minutes=10))]
        self.assertEqual([r["id"] for r in rem.due(races, now, set())], ["600", "603"])
        self.assertEqual(rem.due(races, now, {"600", "603"}), [])
        self.assertEqual(rem.due([race(600, "FP1", FP1)], FP1, set()), [])  # started: too late
        self.assertEqual(rem.due([race(600, "FP1", FP1)], FP1 - timedelta(minutes=16), set()), [])

    def test_dry_run_sends_nothing(self):
        sent = []
        st = Store()
        probs = rem.run_pass(FP1 - timedelta(minutes=14), lambda a, b: [race(600, "FP1", FP1)], st, sent.append, False)
        self.assertEqual((sent, probs, st.marked), ([], [], []))

    def test_sends_once_and_records(self):
        sent = []
        st = Store()
        for minute in (15, 13, 11):
            rem.run_pass(FP1 - timedelta(minutes=minute), lambda a, b: [race(600, "FP1", FP1)], st, sent.append, True)
        self.assertEqual(len(sent), 1); self.assertEqual(st.marked, ["600"])

    def test_no_record_means_no_send(self):
        sent = []
        probs = rem.run_pass(FP1 - timedelta(minutes=14), lambda a, b: [race(600, "FP1", FP1)], Store(fail_load=True), sent.append, True)
        self.assertEqual(sent, []); self.assertTrue(probs)

    def test_too_many_due_sends_nothing(self):
        sent = []
        races = [race(i, "FP1", FP1) for i in range(3)]
        probs = rem.run_pass(FP1 - timedelta(minutes=5), lambda a, b: races, Store(), sent.append, True)
        self.assertEqual(sent, []); self.assertTrue(probs)

    def test_results_push_uses_plain_session_names(self):
        gp = race(1, "Race", FP1)["attributes"]["grandPrix"]["data"]
        gp["attributes"]["track"]["data"]["attributes"]["name"] = "Algarve"
        self.assertEqual(get_title_body_for_notification(gp, "QNR2")[0], "PORTUGAL GP: Qualifying Results Out!")
        self.assertEqual(get_title_body_for_notification(gp, "PRACTICE")[0], "PORTUGAL GP: Practice Results Out!")


if __name__ == "__main__":
    unittest.main()
