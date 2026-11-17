"""
Instagram DM -> Reel reposting bot (Meta Graph API).

Accounts are configured in accounts.toml. When an allowed sender DMs one of those accounts
a reel link (or shares a reel with it):
  1. the Messaging webhook delivers the DM here,
  2. the video is downloaded,
  3. it is published as a Reel on the account that received the DM
     (Instagram fetches the file from PUBLIC_URL/media/...),
  4. the sender gets a DM reply with the result.

Run:  python app.py        Setup: see README.md
"""

import hashlib
import hmac
import json
import logging
import os
import queue
import secrets
import sys
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import requests
from dotenv import load_dotenv
from flask import Flask, abort, jsonify, request, send_file

from accounts import Account, AccountStore, ConfigError
from downloader import DownloadError, download, find_instagram_url
from instagram_api import InstagramError

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Server-wide settings (.env). Per-account settings live in accounts.toml.
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "omvrti123")
APP_SECRET = os.getenv("APP_SECRET", "").strip()
PUBLIC_URL = os.getenv("PUBLIC_URL", "").strip().rstrip("/")
DRY_RUN = os.getenv("DRY_RUN", "false").strip().lower() in ("1", "true", "yes")
API_VERSION = os.getenv("GRAPH_API_VERSION", "v27.0")
COOKIES_FILE = os.getenv("INSTAGRAM_COOKIES_FILE", "").strip() or None
PORT = int(os.getenv("PORT", "5000"))
ACCOUNTS_FILE = BASE_DIR / os.getenv("ACCOUNTS_FILE", "accounts.toml")
DOWNLOAD_DIR = BASE_DIR / "downloads"

# DM attachment types that carry a video URL: shared reels/posts, or a video sent directly.
VIDEO_ATTACHMENT_TYPES = {"ig_reel", "reel", "share", "ig_post", "video"}
HELP_TEXT = "Send me an Instagram reel link (or share a reel here) and I'll post it."

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("reel-bot")

app = Flask(__name__)
accounts = AccountStore(ACCOUNTS_FILE, API_VERSION)
jobs: "queue.Queue[Job]" = queue.Queue()
media_files: dict[str, Path] = {}  # secret token -> video, served only while Instagram fetches it
_seen_mids: "OrderedDict[str, None]" = OrderedDict()
_seen_lock = threading.Lock()


@dataclass
class Job:
    account: Account  # the account that received the DM; it replies and posts
    sender_id: str
    source_url: str | None  # None: the message had no reel, reply with help text
    caption: str = ""


# ---------------------------------------------------------------- helpers

def signature_is_valid(raw_body: bytes, header: str) -> bool:
    if not header.startswith("sha256="):
        return False
    expected = hmac.new(APP_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def first_time_seen(mid: str) -> bool:
    """Meta may deliver the same webhook more than once; process each message once."""
    with _seen_lock:
        if mid in _seen_mids:
            return False
        _seen_mids[mid] = None
        if len(_seen_mids) > 2000:
            _seen_mids.popitem(last=False)
        return True


def short(err: Exception, limit: int = 300) -> str:
    text = str(err)
    return text if len(text) <= limit else text[:limit] + "..."


def reply(job: Job, text: str) -> None:
    try:
        job.account.api.send_text(job.account.ig_id, job.sender_id, text)
    except InstagramError as e:
        logger.warning("[%s] Could not reply to %s: %s", job.account.name, job.sender_id, e)


def build_caption(user_text: str, creator: str | None) -> str:
    parts = [user_text] if user_text else []
    if creator:
        parts.append(f"🎥 @{creator}")
    return "\n\n".join(parts)[:2200]  # Instagram caption limit


def jobs_from_payload(payload: dict):
    if payload.get("object") != "instagram":
        return
    known = accounts.get()
    for entry in payload.get("entry", []):
        ig_id = str(entry.get("id") or "")  # the Instagram account that received the DM
        account = known.get(ig_id)
        for event in entry.get("messaging", []):
            msg = event.get("message") or {}
            sender_id = (event.get("sender") or {}).get("id")
            if not msg or not sender_id or msg.get("is_echo") or msg.get("is_deleted"):
                continue  # read receipts, reactions, our own replies, deletions
            if msg.get("mid") and not first_time_seen(msg["mid"]):
                continue
            if account is None:
                logger.warning("DM to Instagram account %s, which is not in %s (sender %s). "
                               "Add the account there to use it.", ig_id, ACCOUNTS_FILE.name, sender_id)
                continue
            if not account.enabled:
                logger.info("[%s] Ignoring DM: account is disabled in %s.", account.name, ACCOUNTS_FILE.name)
                continue
            if not account.allows(sender_id):
                # Sender IDs are per account: the same person has a different ID on each account.
                logger.warning("Ignoring DM to [%s] from sender %s. To allow it, add the ID to "
                               "allowed_senders for this account in %s.", account.name, sender_id,
                               ACCOUNTS_FILE.name)
                continue

            text = msg.get("text") or ""
            url = find_instagram_url(text)
            if url:
                yield Job(account, sender_id, url, caption=text.replace(url, "").strip())
                continue
            attachment = next((a for a in msg.get("attachments") or []
                               if a.get("type") in VIDEO_ATTACHMENT_TYPES
                               and (a.get("payload") or {}).get("url")), None)
            if attachment:
                payload_url = attachment["payload"]["url"]
                # A shared reel may arrive as an instagram.com link or as a direct video URL.
                yield Job(account, sender_id, find_instagram_url(payload_url) or payload_url)
            else:
                yield Job(account, sender_id, None)


# ---------------------------------------------------------------- worker

def process(job: Job) -> None:
    account = job.account
    if job.source_url is None:
        reply(job, HELP_TEXT)
        return

    logger.info("[%s] Downloading %s (requested by %s)", account.name, job.source_url, job.sender_id)
    reply(job, "Got it! Downloading the reel...")
    try:
        video = download(job.source_url, DOWNLOAD_DIR, COOKIES_FILE)
    except DownloadError as e:
        logger.warning("[%s] Download failed: %s", account.name, e)
        reply(job, f"Couldn't download that reel: {short(e)}\n\n"
                   "If you shared it, try sending the link instead (Share > Copy link).")
        return

    caption = build_caption(job.caption, video.username)
    logger.info("[%s] Downloaded %s", account.name, video.path)
    dry_run = DRY_RUN if account.dry_run is None else account.dry_run
    if dry_run:
        logger.info("[%s] Dry run, not publishing. Caption would be: %r", account.name, caption)
        reply(job, f"Downloaded {video.path.name}. Dry run is on, so it was not posted.")
        return
    if not PUBLIC_URL:
        logger.error("PUBLIC_URL is not set; Instagram needs it to fetch the video.")
        reply(job, "Downloaded, but the bot isn't configured to publish yet (PUBLIC_URL missing).")
        return

    reply(job, "Downloaded. Uploading to Instagram, this can take a minute...")
    token = secrets.token_urlsafe(24)
    media_files[token] = video.path
    try:
        media_id, permalink = account.api.publish_reel(account.ig_id, f"{PUBLIC_URL}/media/{token}.mp4", caption)
    except InstagramError as e:
        logger.error("[%s] Publishing failed: %s", account.name, e)
        reply(job, f"Downloaded, but publishing failed: {short(e)}")
        return
    finally:
        media_files.pop(token, None)

    logger.info("[%s] Published reel %s %s", account.name, media_id, permalink or "")
    video.path.unlink(missing_ok=True)
    reply(job, f"Posted! {permalink}" if permalink else "Posted!")


def worker() -> None:
    while True:
        job = jobs.get()
        try:
            process(job)
        except Exception:
            logger.exception("Unexpected error while processing %s", job)
        finally:
            jobs.task_done()


# ---------------------------------------------------------------- routes

@app.route("/", methods=["GET"])
def health():
    active = sum(1 for a in accounts.get().values() if a.enabled)
    return jsonify(status="ok", accounts=active, dry_run=DRY_RUN, queued=jobs.qsize())


@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("Webhook verified successfully.")
        return challenge, 200
    logger.warning("Webhook verification failed. mode=%s", mode)
    return "Forbidden", 403


@app.route("/webhook", methods=["POST"])
def receive_webhook():
    raw = request.get_data()
    if APP_SECRET and not signature_is_valid(raw, request.headers.get("X-Hub-Signature-256", "")):
        logger.warning("Rejected webhook with an invalid X-Hub-Signature-256.")
        return "Invalid signature", 403
    try:
        payload = json.loads(raw or b"{}")
        logger.info("Webhook event: %s", json.dumps(payload))
        for job in jobs_from_payload(payload):
            jobs.put(job)
    except Exception:
        logger.exception("Could not handle webhook payload: %r", raw[:500])
    # Always answer 200 quickly so Meta doesn't retry; the work happens in the worker thread.
    return jsonify(status="ok"), 200


@app.route("/media/<token>.mp4", methods=["GET"])
def serve_media(token: str):
    path = media_files.get(token)
    if path is None or not path.exists():
        abort(404)
    return send_file(path, mimetype="video/mp4", conditional=True)


# ---------------------------------------------------------------- startup

def startup_checks(known: dict[str, Account]) -> None:
    for account in known.values():
        if not account.enabled:
            logger.info("[%s] Disabled.", account.name)
            continue
        try:
            username = account.api.username(account.ig_id)
            limit = account.api.publishing_limit(account.ig_id)
            dry_run = DRY_RUN if account.dry_run is None else account.dry_run
            logger.info("[%s] OK: @%s (%s), can publish (%s of %s posts used in 24h)%s.",
                        account.name, username, account.ig_id, limit.get("quota_usage", "?"),
                        (limit.get("config") or {}).get("quota_total", "?"), ", DRY RUN" if dry_run else "")
        except InstagramError as e:
            logger.error("[%s] Its access_token can't use account %s: %s", account.name, account.ig_id, e)
        if not account.allowed_senders:
            logger.warning("[%s] allowed_senders is empty, so its DMs are ignored. DM the account; "
                           "the log shows the sender ID to add.", account.name)
        elif "*" in account.allowed_senders:
            logger.warning("[%s] allowed_senders is [\"*\"]: ANYONE can get reels posted.", account.name)

    if not APP_SECRET:
        logger.warning("APP_SECRET is not set: webhook signatures are not verified.")
    if not PUBLIC_URL:
        logger.warning("PUBLIC_URL is not set: publishing will not work.")
    else:
        threading.Thread(target=check_public_url, daemon=True).start()


def check_public_url() -> None:
    time.sleep(3)  # give the server a moment to start
    try:
        resp = requests.get(f"{PUBLIC_URL}/", timeout=15)
        ok = resp.ok and resp.headers.get("Content-Type", "").startswith("application/json") \
            and resp.json().get("status") == "ok"
    except (requests.RequestException, ValueError) as e:
        logger.error("PUBLIC_URL %s is not reachable: %s", PUBLIC_URL, e)
        return
    if ok:
        logger.info("PUBLIC_URL %s reaches this app.", PUBLIC_URL)
    else:
        logger.error("PUBLIC_URL %s answered, but not from this app (HTTP %s).", PUBLIC_URL, resp.status_code)


if __name__ == "__main__":
    try:
        known_accounts = accounts.get()
    except ConfigError as e:
        logger.error("%s", e)
        sys.exit(1)
    threading.Thread(target=worker, daemon=True, name="reel-worker").start()
    startup_checks(known_accounts)
    try:
        from waitress import serve
    except ImportError:
        app.run(host="0.0.0.0", port=PORT, threaded=True)
    else:
        logger.info("Listening on http://0.0.0.0:%s", PORT)
        serve(app, host="0.0.0.0", port=PORT, threads=8)
