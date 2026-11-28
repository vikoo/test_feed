import unittest
from unittest import mock

from cron.notifiaction import notification_utils as nu


class PushCollapseIdTest(unittest.TestCase):
    """One push, one card: every language copy of a push carries the same collapse id, so a phone with
    stale FCM registrations (iOS reinstall) shows the push once (Valencia FP2 results, 28 Nov 2026)."""

    def send_all(self, messages):
        sent = []
        with mock.patch.object(nu, "_" + "_init_firebase_admin"), \
                mock.patch.object(nu.messaging, "send", side_effect=lambda m: sent.append(m) or "id"):
            nu.send_localized_notification_to_topic(is_f1=False, is_prod=True, messages=messages)
        return sent

    def test_same_collapse_id_on_ios_and_android_for_every_language(self):
        messages = {"en": ("📊 Valencia GP: FP2 results", "See who topped FP2 👀🔥"),
                    "it": ("📊 Valencia GP: risultati FP2", "Scopri il più veloce delle FP2 👀🔥"),
                    "ja": ("📊 Valencia GP：FP2結果", "FP2トップは誰？ 👀🔥")}
        sent = self.send_all(messages)
        self.assertEqual(len(sent), 3)
        ids = {m.apns.headers["apns-collapse-id"] for m in sent}
        self.assertEqual(len(ids), 1)
        cid = ids.pop()
        self.assertLessEqual(len(cid.encode("utf-8")), 64)  # APNs limit
        for m in sent:
            self.assertEqual(m.android.notification.tag, cid)
            self.assertEqual(m.android.collapse_key, cid)
        self.assertEqual(sorted(m.topic for m in sent),
                         ["wheelie_notification_en", "wheelie_notification_it", "wheelie_notification_ja"])

    def test_different_pushes_get_different_ids(self):
        a = nu.push_collapse_id("📊 Valencia GP: FP2 results", "See who topped FP2 👀🔥")
        b = nu.push_collapse_id("🏁 Valencia GP: Grid is set", "See who took pole 👀🔥")
        c = nu.push_collapse_id("📊 Portugal GP: FP2 results", "See who topped FP2 👀🔥")
        self.assertEqual(len({a, b, c}), 3)
        self.assertEqual(a, nu.push_collapse_id("📊 Valencia GP: FP2 results", "See who topped FP2 👀🔥"))

    def test_refused_label_still_sends_the_plain_push(self):
        from firebase_admin import exceptions as fe
        calls = []

        def send(m):
            calls.append((m.apns, m.android))
            if m.apns is not None:
                raise fe.InvalidArgumentError("bad apns header")
            return "id"
        with mock.patch.object(nu, "_" + "_init_firebase_admin"), mock.patch.object(nu.messaging, "send", side_effect=send):
            nu.send_localized_notification_to_topic(is_f1=False, is_prod=True,
                                                    messages={"en": ("📊 Valencia GP: FP2 results", "See who topped FP2 👀🔥")})
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1], (None, None))

    def test_other_errors_are_not_resent(self):
        # A timeout may mean FCM delivered it: resending would double the push, so it raises as before.
        from firebase_admin import exceptions as fe
        with mock.patch.object(nu, "_" + "_init_firebase_admin"), \
                mock.patch.object(nu.messaging, "send", side_effect=fe.DeadlineExceededError("timeout")) as send:
            with self.assertRaises(fe.DeadlineExceededError):
                nu.send_localized_notification_to_topic(is_f1=False, is_prod=True,
                                                        messages={"en": ("📊 Valencia GP: FP2 results", "See who topped FP2 👀🔥")})
        self.assertEqual(send.call_count, 1)

    def test_firebase_accepts_the_message(self):
        # Builds the real request body the Admin SDK would post; fails on a bad APNs/Android field.
        from firebase_admin._messaging_encoder import MessageEncoder
        sent = self.send_all({"en": ("📊 Valencia GP: FP2 results", "See who topped FP2 👀🔥")})
        body = MessageEncoder().default(sent[0])
        self.assertEqual(body["apns"]["headers"]["apns-collapse-id"], sent[0].apns.headers["apns-collapse-id"])
        self.assertEqual(body["android"]["notification"]["tag"], sent[0].android.notification.tag)


if __name__ == "__main__":
    unittest.main()
