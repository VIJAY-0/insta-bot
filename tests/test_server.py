import hashlib
import hmac
import json
import tempfile
import unittest
from pathlib import Path

from reelbot.accounts import AccountStore
from reelbot.bot import ReelBot
from reelbot.config import Settings
from reelbot.server import create_app

from .helpers import ACCOUNTS_TOML, dm_payload

REEL = "https://www.instagram.com/reel/ABC/"


class ServerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        (self.dir / "accounts.toml").write_text(ACCOUNTS_TOML, encoding="utf-8")
        self.client = self.make_client()

    def make_client(self, **settings):
        settings = Settings(**{"verify_token": "tok", "app_secret": "", "download_dir": self.dir, **settings})
        self.bot = ReelBot(settings, AccountStore(self.dir / "accounts.toml", "v27.0"))
        return create_app(self.bot).test_client()

    def post(self, payload: dict, secret: str | None = None, signature: str | None = None):
        body = json.dumps(payload).encode()
        if secret is not None:
            signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        headers = {"X-Hub-Signature-256": signature} if signature else {}
        return self.client.post("/webhook", data=body, headers=headers, content_type="application/json")

    def test_health(self):
        self.assertEqual(self.client.get("/").get_json(),
                         {"status": "ok", "accounts": 1, "dry_run": False, "queued": 0})

    def test_verify_webhook(self):
        resp = self.client.get("/webhook?hub.mode=subscribe&hub.verify_token=tok&hub.challenge=123")
        self.assertEqual((resp.status_code, resp.text, resp.mimetype), (200, "123", "text/plain"))

    def test_verify_webhook_rejects_wrong_or_unset_token(self):
        with self.assertLogs("reelbot.server", "WARNING"):
            resp = self.client.get("/webhook?hub.mode=subscribe&hub.verify_token=nope&hub.challenge=1")
        self.assertEqual(resp.status_code, 403)

        client = self.make_client(verify_token="")
        with self.assertLogs("reelbot.server", "WARNING"):
            resp = client.get("/webhook?hub.mode=subscribe&hub.verify_token=&hub.challenge=1")
        self.assertEqual(resp.status_code, 403)

    def test_dm_is_queued(self):
        self.assertEqual(self.post(dm_payload(REEL)).status_code, 200)
        self.assertEqual(self.bot.jobs.get_nowait().source_url, REEL)

    def test_signature_is_checked_when_app_secret_is_set(self):
        self.client = self.make_client(app_secret="s3cret")
        with self.assertLogs("reelbot.server", "WARNING"):
            self.assertEqual(self.post(dm_payload(REEL), signature="sha256=bad").status_code, 403)
            self.assertEqual(self.post(dm_payload(REEL)).status_code, 403)
        self.assertTrue(self.bot.jobs.empty())

        self.assertEqual(self.post(dm_payload(REEL), secret="s3cret").status_code, 200)
        self.assertEqual(self.bot.jobs.qsize(), 1)

    def test_bad_payload_still_gets_200(self):
        with self.assertLogs("reelbot.server", "ERROR"):
            resp = self.client.post("/webhook", data=b"not json")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(self.bot.jobs.empty())

    def test_media_is_served_only_while_exposed(self):
        video = self.dir / "v.mp4"
        video.write_bytes(b"video-bytes")
        with self.bot.media.expose(video) as token:
            resp = self.client.get(f"/media/{token}.mp4")
            self.assertEqual((resp.status_code, resp.data, resp.mimetype), (200, b"video-bytes", "video/mp4"))
            resp.close()
        self.assertEqual(self.client.get(f"/media/{token}.mp4").status_code, 404)
