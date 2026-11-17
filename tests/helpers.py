"""Test doubles and builders shared by the tests. Nothing here talks to the network."""

from reelbot.accounts import Account

IG_ID = "17841400000000001"
SENDER = "42"


class FakeAPI:
    """Stands in for InstagramAPI: records DMs and publishes instead of calling Instagram."""

    def __init__(self, permalink: str | None = "https://www.instagram.com/reel/NEW/",
                 publish_error: Exception | None = None, on_publish=None):
        self.sent: list[str] = []
        self.published: list[tuple[str, str]] = []  # (video_url, caption)
        self.permalink = permalink
        self.publish_error = publish_error
        self.on_publish = on_publish  # called with video_url while the "upload" is in progress

    def send_text(self, ig_id: str, recipient_id: str, text: str) -> dict:
        self.sent.append(text)
        return {}

    def publish_reel(self, ig_id: str, video_url: str, caption: str = "") -> tuple[str, str | None]:
        if self.on_publish:
            self.on_publish(video_url)
        if self.publish_error:
            raise self.publish_error
        self.published.append((video_url, caption))
        return "media-1", self.permalink


def make_account(**overrides) -> Account:
    fields = {"name": "main", "ig_id": IG_ID, "api": FakeAPI(), "allowed_senders": {SENDER}}
    fields.update(overrides)
    return Account(**fields)


def dm_payload(text: str | None = None, attachments: list | None = None, *, mid: str = "m1",
               sender: str = SENDER, ig_id: str = IG_ID, **message_fields) -> dict:
    """A Messaging webhook payload carrying one DM."""
    message = {"mid": mid, **message_fields}
    if text is not None:
        message["text"] = text
    if attachments is not None:
        message["attachments"] = attachments
    return {"object": "instagram",
            "entry": [{"id": ig_id, "messaging": [{"sender": {"id": sender}, "message": message}]}]}


ACCOUNTS_TOML = f"""
[accounts.main]
ig_account_id = "{IG_ID}"
access_token = "EAA-test"
allowed_senders = ["{SENDER}"]
"""
