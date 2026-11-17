import unittest

from reelbot.messages import SeenMessages, iter_jobs, reel_request

from .helpers import IG_ID, SENDER, dm_payload, make_account

REEL = "https://www.instagram.com/reel/ABC123/?igsh=xyz"


class ReelRequestTest(unittest.TestCase):
    def test_link_with_text_uses_text_as_caption(self):
        self.assertEqual(reel_request({"text": f"Monday mood {REEL}"}), (REEL, "Monday mood"))

    def test_shared_reel_with_instagram_link(self):
        message = {"attachments": [{"type": "ig_reel", "payload": {"url": f"{REEL} extra"}}]}
        self.assertEqual(reel_request(message), (REEL, ""))

    def test_shared_video_with_direct_url(self):
        url = "https://lookaside.fbsbx.com/ig_messaging_cdn/?asset_id=1"
        self.assertEqual(reel_request({"attachments": [{"type": "video", "payload": {"url": url}}]}), (url, ""))

    def test_ignores_attachments_without_video(self):
        message = {"attachments": [{"type": "image", "payload": {"url": "https://x/1.jpg"}},
                                   {"type": "share", "payload": {}}]}
        self.assertEqual(reel_request(message), (None, ""))

    def test_plain_text(self):
        self.assertEqual(reel_request({"text": "hello"}), (None, ""))


class IterJobsTest(unittest.TestCase):
    def setUp(self):
        self.account = make_account()
        self.accounts = {IG_ID: self.account}
        self.seen = SeenMessages()

    def jobs(self, payload, accounts=None):
        return list(iter_jobs(payload, self.accounts if accounts is None else accounts, self.seen))

    def test_reel_link(self):
        [job] = self.jobs(dm_payload(f"nice {REEL}"))
        self.assertIs(job.account, self.account)
        self.assertEqual((job.sender_id, job.source_url, job.caption), (SENDER, REEL, "nice"))

    def test_message_without_reel_gets_a_help_job(self):
        [job] = self.jobs(dm_payload("hi"))
        self.assertIsNone(job.source_url)

    def test_skips_echoes_deletions_and_non_messages(self):
        self.assertEqual(self.jobs(dm_payload(REEL, is_echo=True)), [])
        self.assertEqual(self.jobs(dm_payload(REEL, mid="m2", is_deleted=True)), [])
        read_receipt = {"object": "instagram",
                        "entry": [{"id": IG_ID, "messaging": [{"sender": {"id": SENDER}, "read": {}}]}]}
        self.assertEqual(self.jobs(read_receipt), [])
        self.assertEqual(self.jobs({"object": "page", "entry": []}), [])

    def test_duplicate_deliveries_are_processed_once(self):
        self.assertEqual(len(self.jobs(dm_payload(REEL, mid="same"))), 1)
        self.assertEqual(self.jobs(dm_payload(REEL, mid="same")), [])

    def test_unknown_account_is_logged(self):
        with self.assertLogs("reelbot.messages", "WARNING") as logs:
            self.assertEqual(self.jobs(dm_payload(REEL, ig_id="999")), [])
        self.assertIn("999", logs.output[0])

    def test_disabled_account(self):
        accounts = {IG_ID: make_account(enabled=False)}
        with self.assertLogs("reelbot.messages", "INFO"):
            self.assertEqual(self.jobs(dm_payload(REEL), accounts), [])

    def test_sender_not_allowed_is_logged_with_its_id(self):
        with self.assertLogs("reelbot.messages", "WARNING") as logs:
            self.assertEqual(self.jobs(dm_payload(REEL, sender="7")), [])
        self.assertIn("sender 7", logs.output[0])

    def test_wildcard_allows_anyone(self):
        accounts = {IG_ID: make_account(allowed_senders={"*"})}
        self.assertEqual(len(self.jobs(dm_payload(REEL, sender="7"), accounts)), 1)


class SeenMessagesTest(unittest.TestCase):
    def test_forgets_oldest_beyond_limit(self):
        seen = SeenMessages(limit=2)
        for mid in ("a", "b", "c"):
            self.assertTrue(seen.first_time(mid))
        self.assertTrue(seen.first_time("a"))  # evicted, so it counts as new again
        self.assertFalse(seen.first_time("c"))
