"""The reel pipeline: queue jobs, download each video, publish it, and reply to the sender."""

import logging
import queue
import secrets
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .accounts import AccountStore
from .captions import pick_caption
from .config import Settings
from .downloader import DownloadError, Video, download
from .instagram import InstagramError
from .messages import Job, SeenMessages, iter_jobs

logger = logging.getLogger(__name__)

HELP_TEXT = "Send me an Instagram reel link (or share a reel here) and I'll post it."


class MediaHost:
    """Videos served at PUBLIC_URL/media/<token>.mp4, only while Instagram fetches them."""

    def __init__(self):
        self._files: dict[str, Path] = {}

    @contextmanager
    def expose(self, path: Path) -> Iterator[str]:
        """Serve path under a fresh secret token for the duration of the with-block."""
        token = secrets.token_urlsafe(24)
        self._files[token] = path
        try:
            yield token
        finally:
            self._files.pop(token, None)

    def get(self, token: str) -> Path | None:
        return self._files.get(token)


class ReelBot:
    def __init__(self, settings: Settings, accounts: AccountStore):
        self.settings = settings
        self.accounts = accounts
        self.media = MediaHost()
        self.jobs: queue.Queue[Job] = queue.Queue()
        self._seen = SeenMessages()

    def enqueue_webhook(self, payload: dict) -> None:
        """Queue a job for each actionable DM in a webhook payload."""
        for job in iter_jobs(payload, self.accounts.get(), self._seen, self.accounts.path.name):
            self.jobs.put(job)

    def start_worker(self) -> threading.Thread:
        """Process queued jobs one at a time in a background thread."""
        thread = threading.Thread(target=self._work, daemon=True, name="reel-worker")
        thread.start()
        return thread

    def _work(self) -> None:
        while True:
            job = self.jobs.get()
            try:
                self.process(job)
            except Exception:
                logger.exception("Unexpected error while processing %s", job)
            finally:
                self.jobs.task_done()

    def process(self, job: Job) -> None:
        account = job.account
        if job.source_url is None:
            _reply(job, HELP_TEXT)
            return

        logger.info("[%s] Downloading %s (requested by %s)", account.name, job.source_url, job.sender_id)
        _reply(job, "Got it! Downloading the reel...")
        try:
            video = download(job.source_url, self.settings.download_dir, self.settings.cookies_file)
        except DownloadError as e:
            logger.warning("[%s] Download failed: %s", account.name, e)
            _reply(job, f"Couldn't download that reel: {_short(e)}\n\n"
                        "If you shared it, try sending the link instead (Share > Copy link).")
            return
        logger.info("[%s] Downloaded %s", account.name, video.path)

        caption = pick_caption(job.caption, video.description)
        if account.dry_run:
            logger.info("[%s] Dry run, not publishing. Caption would be: %r", account.name, caption)
            _reply(job, f"Downloaded {video.path.name}. Dry run is on, so it was not posted.")
            return
        if not self.settings.public_url:
            logger.error("PUBLIC_URL is not set; Instagram needs it to fetch the video.")
            _reply(job, "Downloaded, but the bot isn't configured to publish yet (PUBLIC_URL missing).")
            return
        self._publish(job, video, caption)

    def _publish(self, job: Job, video: Video, caption: str) -> None:
        account = job.account
        _reply(job, "Downloaded. Uploading to Instagram, this can take a minute...")
        try:
            with self.media.expose(video.path) as token:
                video_url = f"{self.settings.public_url}/media/{token}.mp4"
                media_id, permalink = account.api.publish_reel(account.ig_id, video_url, caption)
        except InstagramError as e:
            logger.error("[%s] Publishing failed: %s", account.name, e)
            _reply(job, f"Downloaded, but publishing failed: {_short(e)}")
            return

        logger.info("[%s] Published reel %s %s", account.name, media_id, permalink or "")
        video.path.unlink(missing_ok=True)
        _reply(job, f"Posted! {permalink}" if permalink else "Posted!")


def _reply(job: Job, text: str) -> None:
    """DM the sender from the account they wrote to. Failures are logged, not raised."""
    try:
        job.account.api.send_text(job.account.ig_id, job.sender_id, text)
    except InstagramError as e:
        logger.warning("[%s] Could not reply to %s: %s", job.account.name, job.sender_id, e)


def _short(err: Exception, limit: int = 300) -> str:
    text = str(err)
    return text if len(text) <= limit else text[:limit] + "..."
