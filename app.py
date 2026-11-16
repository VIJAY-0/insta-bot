"""
Instagram DM -> Reel reposting bot (Meta Graph API, Instagram Login).

When an allowed user DMs your Instagram account a reel link (or shares a reel with it):
  1. the Messaging webhook delivers the DM here,
  2. the video is downloaded,
  3. it is published as a Reel on your account (Instagram fetches it from PUBLIC_URL/media/...),
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
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import requests
from dotenv import load_dotenv
from flask import Flask, abort, jsonify, request, send_file

from downloader import DownloadError, download, find_instagram_url
from instagram_api import InstagramAPI, InstagramError

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

ACCESS_TOKEN = (os.getenv("ACCESS_TOKEN") or os.getenv("ACCOUNT_TOKEN") or "").strip()
IG_ACCOUNT_ID = os.getenv("IG_ACCOUNT_ID", "").strip()  # optional; found automatically if possible
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "omvrti123")
APP_SECRET = os.getenv("APP_SECRET", "").strip()
PUBLIC_URL = os.getenv("PUBLIC_URL", "").strip().rstrip("/")
ALLOWED_SENDER_IDS = {s.strip() for s in os.getenv("ALLOWED_SENDER_IDS", "").split(",") if s.strip()}
DRY_RUN = os.getenv("DRY_RUN", "false").strip().lower() in ("1", "true", "yes")
API_VERSION = os.getenv("GRAPH_API_VERSION", "v27.0")
COOKIES_FILE = os.getenv("INSTAGRAM_COOKIES_FILE", "").strip() or None
PORT = int(os.getenv("PORT", "5000"))
DOWNLOAD_DIR = BASE_DIR / "downloads"

# DM attachment types that carry a video URL: shared reels/posts, or a video sent directly.
VIDEO_ATTACHMENT_TYPES = {"ig_reel", "reel", "share", "ig_post", "video"}
HELP_TEXT = "Send me an Instagram reel link (or share a reel here) and I'll post it."

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("reel-bot")

app = Flask(__name__)
api = InstagramAPI(ACCESS_TOKEN, API_VERSION)
jobs: "queue.Queue[Job]" = queue.Queue()
media_files: dict[str, Path] = {}  # secret token -> video, served only while Instagram fetches it
_account: dict[str, str | None] = {"id": IG_ACCOUNT_ID or None, "username": None}
_seen_mids: "OrderedDict[str, None]" = OrderedDict()
_seen_lock = threading.Lock()


@dataclass
class Job:
    sender_id: str
    source_url: str | None  # None: the message had no reel, reply with help text
    caption: str = ""


# ---------------------------------------------------------------- helpers

def account_id() -> str:
    """Our Instagram account ID: from IG_ACCOUNT_ID, the token, or the first incoming webhook."""
    if not _account["id"]:
        _account["id"] = api.find_account_id()
    if not _account["id"]:
        raise InstagramError("Instagram account ID unknown. Set IG_ACCOUNT_ID in .env, "
                             "or DM the account once so the bot can learn it.")
    if not _account["username"]:
        try:
            _account["username"] = api.username(_account["id"])
        except InstagramError as e:
            logger.warning("Could not read the account's username: %s", e)
    return _account["id"]


def learn_account_id(ig_id: str | None) -> None:
    if ig_id and not _account["id"]:
        _account["id"] = str(ig_id)
        logger.info("Learned Instagram account ID %s from a webhook. "
                    "Add IG_ACCOUNT_ID=%s to .env to keep it across restarts.", ig_id, ig_id)


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


def sender_allowed(sender_id: str) -> bool:
    return "*" in ALLOWED_SENDER_IDS or sender_id in ALLOWED_SENDER_IDS


def short(err: Exception, limit: int = 300) -> str:
    text = str(err)
    return text if len(text) <= limit else text[:limit] + "..."


def reply(user_id: str, text: str) -> None:
    try:
        api.send_text(account_id(), user_id, text)
    except InstagramError as e:
        logger.warning("Could not reply to %s: %s", user_id, e)


def build_caption(user_text: str, creator: str | None) -> str:
    parts = [user_text] if user_text else []
    if creator:
        parts.append(f"🎥 @{creator}")
    return "\n\n".join(parts)[:2200]  # Instagram caption limit


def jobs_from_payload(payload: dict):
    if payload.get("object") != "instagram":
        return
    for entry in payload.get("entry", []):
        learn_account_id(entry.get("id"))  # entry.id is our own Instagram account ID
        for event in entry.get("messaging", []):
            msg = event.get("message") or {}
            sender_id = (event.get("sender") or {}).get("id")
            if not msg or not sender_id or msg.get("is_echo") or msg.get("is_deleted"):
                continue  # read receipts, reactions, our own replies, deletions
            if msg.get("mid") and not first_time_seen(msg["mid"]):
                continue
            if not sender_allowed(sender_id):
                logger.warning("Ignoring DM from sender %s (not in ALLOWED_SENDER_IDS). "
                               "Add this ID to .env if they should be able to post.", sender_id)
                continue

            text = msg.get("text") or ""
            url = find_instagram_url(text)
            if url:
                yield Job(sender_id, url, caption=text.replace(url, "").strip())
                continue
            attachment = next((a for a in msg.get("attachments") or []
                               if a.get("type") in VIDEO_ATTACHMENT_TYPES
                               and (a.get("payload") or {}).get("url")), None)
            if attachment:
                payload_url = attachment["payload"]["url"]
                # A shared reel may arrive as an instagram.com link or as a direct video URL.
                yield Job(sender_id, find_instagram_url(payload_url) or payload_url)
            else:
                yield Job(sender_id, None)


# ---------------------------------------------------------------- worker

def process(job: Job) -> None:
    if job.source_url is None:
        reply(job.sender_id, HELP_TEXT)
        return

    logger.info("Downloading %s (requested by %s)", job.source_url, job.sender_id)
    reply(job.sender_id, "Got it! Downloading the reel...")
    try:
        video = download(job.source_url, DOWNLOAD_DIR, COOKIES_FILE)
    except DownloadError as e:
        logger.warning("Download failed: %s", e)
        reply(job.sender_id, f"Couldn't download that reel: {short(e)}\n\n"
                             "If you shared it, try sending the link instead (Share > Copy link).")
        return

    caption = build_caption(job.caption, video.username)
    logger.info("Downloaded %s", video.path)
    if DRY_RUN:
        logger.info("DRY_RUN is on, not publishing. Caption would be: %r", caption)
        reply(job.sender_id, f"Downloaded {video.path.name}. Dry run is on, so it was not posted.")
        return
    if not PUBLIC_URL:
        logger.error("PUBLIC_URL is not set; Instagram needs it to fetch the video.")
        reply(job.sender_id, "Downloaded, but the bot isn't configured to publish yet (PUBLIC_URL missing).")
        return

    reply(job.sender_id, "Downloaded. Uploading to Instagram, this can take a minute...")
    token = secrets.token_urlsafe(24)
    media_files[token] = video.path
    try:
        media_id, permalink = api.publish_reel(account_id(), f"{PUBLIC_URL}/media/{token}.mp4", caption)
    except InstagramError as e:
        logger.error("Publishing failed: %s", e)
        reply(job.sender_id, f"Downloaded, but publishing failed: {short(e)}")
        return
    finally:
        media_files.pop(token, None)

    logger.info("Published reel %s %s", media_id, permalink or "")
    video.path.unlink(missing_ok=True)
    reply(job.sender_id, f"Posted! {permalink}" if permalink else "Posted!")


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
    return jsonify(status="ok", account=_account["username"], dry_run=DRY_RUN, queued=jobs.qsize())


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

def startup_checks() -> None:
    if not ACCESS_TOKEN:
        logger.error("ACCESS_TOKEN is missing from .env.")
    else:
        logger.info("Using %s.", api.base.rsplit("/", 1)[0])
        try:
            ig_id = account_id()
            logger.info("Connected to Instagram as @%s (account id %s).", _account["username"], ig_id)
            limit = api.publishing_limit(ig_id)
            logger.info("Publishing permission OK (%s of %s posts used in the last 24h).",
                        limit.get("quota_usage", "?"), (limit.get("config") or {}).get("quota_total", "?"))
        except InstagramError as e:
            logger.error("Instagram setup problem: %s", e)

    if not ALLOWED_SENDER_IDS:
        logger.warning("ALLOWED_SENDER_IDS is empty, so every DM will be ignored. "
                       "DM the account once; the log will show your sender ID to add.")
    elif "*" in ALLOWED_SENDER_IDS:
        logger.warning("ALLOWED_SENDER_IDS=* : ANYONE who DMs a reel link can get it posted.")
    if DRY_RUN:
        logger.warning("DRY_RUN is on: reels are downloaded but NOT published.")
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
    threading.Thread(target=worker, daemon=True, name="reel-worker").start()
    startup_checks()
    try:
        from waitress import serve
    except ImportError:
        app.run(host="0.0.0.0", port=PORT, threaded=True)
    else:
        logger.info("Listening on http://0.0.0.0:%s", PORT)
        serve(app, host="0.0.0.0", port=PORT, threads=8)
