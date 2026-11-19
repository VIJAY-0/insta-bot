import tempfile
import unittest
from pathlib import Path
from unittest import mock

from reelbot.accounts import AccountStore
from reelbot.bot import HELP_TEXT, ReelBot
from reelbot.captions import CAPTION_LIMIT, GTA_CAPTIONS, pick_caption
from reelbot.config import Settings
from reelbot.downloader import DownloadError, Video
from reelbot.instagram import InstagramError
from reelbot.messages import Job

from .helpers import SENDER, FakeAPI, make_account

PUBLIC_URL = "https://bot.example.com"


class ProcessTest(unittest.TestCase):
    """ReelBot.process with a fake Instagram API and a patched download()."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.video = Video(self.dir / "ABC.mp4", username="creator", description="Original caption")
        self.video.path.write_bytes(b"video")

    def run_job(self, account=None, source_url="https://www.instagram.com/reel/ABC/", caption="",
                public_url=PUBLIC_URL, download_result=None):
        account = account or make_account()
        settings = Settings(public_url=public_url, download_dir=self.dir)
        self.bot = ReelBot(settings, AccountStore(self.dir / "accounts.toml", "v27.0"))
        downloaded = mock.Mock(side_effect=[download_result or self.video])
        with mock.patch("reelbot.bot.download", downloaded), self.assertLogs("reelbot.bot", "INFO"):
            self.bot.process(Job(account, SENDER, source_url, caption))
        return account.api

    def test_message_without_reel_gets_help(self):
        api = FakeAPI()
        settings = Settings(download_dir=self.dir)
        bot = ReelBot(settings, AccountStore(self.dir / "accounts.toml", "v27.0"))
        bot.process(Job(make_account(api=api), SENDER, None))
        self.assertEqual(api.sent, [HELP_TEXT])

    def test_publishes_and_replies_with_permalink(self):
        served = []
        api = FakeAPI(on_publish=lambda url: served.append(self.bot.media.get(url.rsplit("/", 1)[1][:-4])))
        self.run_job(make_account(api=api), caption="Monday mood")

        [(video_url, caption)] = api.published
        self.assertTrue(video_url.startswith(f"{PUBLIC_URL}/media/") and video_url.endswith(".mp4"))
        self.assertEqual(caption, "Monday mood")
        self.assertEqual(served, [self.video.path])  # reachable while Instagram fetches it...
        self.assertEqual(self.bot.media._files, {})  # ...and not afterwards
        self.assertFalse(self.video.path.exists())
        self.assertEqual(api.sent[-1], "Posted! https://www.instagram.com/reel/NEW/")

    def test_dry_run_downloads_but_does_not_publish(self):
        api = self.run_job(make_account(api=FakeAPI(), dry_run=True))
        self.assertEqual(api.published, [])
        self.assertTrue(self.video.path.exists())
        self.assertIn("Dry run is on", api.sent[-1])

    def test_download_failure(self):
        api = self.run_job(download_result=DownloadError("private account"))
        self.assertIn("Couldn't download that reel: private account", api.sent[-1])

    def test_missing_public_url(self):
        api = self.run_job(public_url="")
        self.assertEqual(api.published, [])
        self.assertIn("PUBLIC_URL missing", api.sent[-1])

    def test_publish_failure_keeps_the_video(self):
        api = FakeAPI(publish_error=InstagramError("quota reached"))
        self.run_job(make_account(api=api))
        self.assertTrue(self.video.path.exists())
        self.assertEqual(self.bot.media._files, {})
        self.assertIn("publishing failed: quota reached", api.sent[-1])


class PickCaptionTest(unittest.TestCase):
    def test_prefers_the_senders_text_then_the_original_caption(self):
        self.assertEqual(pick_caption(" hi ", "Original"), "hi")
        self.assertEqual(pick_caption("", "Original\n#tag"), "Original\n#tag")
        self.assertEqual(pick_caption("  ", "Original"), "Original")

    def test_falls_back_to_a_random_gta_caption(self):
        for original in (None, "", "  \n"):
            self.assertIn(pick_caption("", original), GTA_CAPTIONS)

    def test_never_credits_the_creator(self):
        for caption in GTA_CAPTIONS:
            self.assertNotIn("@", caption)

    def test_truncates_to_instagram_limit(self):
        self.assertEqual(len(pick_caption("x" * 3000, None)), CAPTION_LIMIT)
