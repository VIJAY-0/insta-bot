"""HTTP endpoints: health check, Meta's webhook, and the temporary video URLs Instagram fetches."""

import hashlib
import hmac
import json
import logging

from flask import Flask, abort, jsonify, request, send_file

from .bot import ReelBot

logger = logging.getLogger(__name__)


def signature_is_valid(app_secret: str, raw_body: bytes, header: str) -> bool:
    """Check Meta's X-Hub-Signature-256 header: sha256=<HMAC-SHA256 of the body with the app secret>."""
    if not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def create_app(bot: ReelBot) -> Flask:
    app = Flask(__name__)
    settings = bot.settings

    @app.get("/")
    def health():
        active = sum(1 for a in bot.accounts.get().values() if a.enabled)
        return jsonify(status="ok", accounts=active, dry_run=settings.dry_run, queued=bot.jobs.qsize())

    @app.get("/webhook")
    def verify_webhook():
        """Meta calls this when the webhook is configured; echo the challenge if the token matches."""
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        if mode == "subscribe" and settings.verify_token and token == settings.verify_token:
            logger.info("Webhook verified successfully.")
            return request.args.get("hub.challenge", ""), 200, {"Content-Type": "text/plain"}
        logger.warning("Webhook verification failed. mode=%s", mode)
        return "Forbidden", 403

    @app.post("/webhook")
    def receive_webhook():
        raw = request.get_data()
        signature = request.headers.get("X-Hub-Signature-256", "")
        if settings.app_secret and not signature_is_valid(settings.app_secret, raw, signature):
            logger.warning("Rejected webhook with an invalid X-Hub-Signature-256.")
            return "Invalid signature", 403
        try:
            payload = json.loads(raw or b"{}")
            logger.info("Webhook event: %s", json.dumps(payload))
            bot.enqueue_webhook(payload)
        except Exception:
            logger.exception("Could not handle webhook payload: %r", raw[:500])
        # Always answer 200 quickly so Meta doesn't retry; the work happens in the worker thread.
        return jsonify(status="ok"), 200

    @app.get("/media/<token>.mp4")
    def serve_media(token: str):
        path = bot.media.get(token)
        if path is None or not path.exists():
            abort(404)
        return send_file(path, mimetype="video/mp4", conditional=True)

    return app
