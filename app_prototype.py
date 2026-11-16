"""
Instagram Messaging API (Meta Graph API) webhook receiver.

To expose this locally for Meta's webhook configuration, run:
    ngrok http 5000
Then use the ngrok https URL (e.g. https://xxxx.ngrok.io/webhook) as the
Callback URL in the Meta App Dashboard, with Verify Token = omvrti123.
"""

import json
import logging

from flask import Flask, request, jsonify

app = Flask(__name__)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("instagram-webhook")

VERIFY_TOKEN = "omvrti123"


@app.route("/webhook", methods=["GET"])
def verify_webhook():
    try:
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")

        if mode == "subscribe" and token == VERIFY_TOKEN:
            logger.info("Webhook verified successfully.")
            return challenge, 200

        logger.warning("Webhook verification failed. mode=%s token=%s", mode, token)
        return "Forbidden", 403
    except Exception:
        logger.exception("Error during webhook verification.")
        return "Bad Request", 400


@app.route("/webhook", methods=["POST"])
def receive_webhook():
    try:
        payload = request.get_json(silent=True, force=True)

        print("\n" + "=" * 60)
        print("INCOMING WEBHOOK EVENT")
        print("=" * 60)
        if payload is not None:
            print(json.dumps(payload, indent=2))
        else:
            print("<no JSON body received>")
            print(request.data.decode("utf-8", errors="replace"))
        print("=" * 60 + "\n")
    except Exception:
        logger.exception("Error while processing incoming webhook payload.")

    # Always return 200 immediately so Meta doesn't retry/timeout.
    return jsonify(status="ok"), 200


@app.errorhandler(Exception)
def handle_unexpected_error(err):
    logger.exception("Unhandled exception: %s", err)
    return jsonify(error="internal_server_error"), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
