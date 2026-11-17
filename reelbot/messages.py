"""Turn Instagram Messaging webhook payloads into reel jobs."""

import logging
import threading
from collections import OrderedDict
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from .accounts import Account
from .downloader import find_instagram_url

logger = logging.getLogger(__name__)

# DM attachment types that carry a video URL: shared reels/posts, or a video sent directly.
VIDEO_ATTACHMENT_TYPES = {"ig_reel", "reel", "share", "ig_post", "video"}


@dataclass
class Job:
    account: Account  # the account that received the DM; it replies and posts
    sender_id: str
    source_url: str | None  # None: the message had no reel, reply with help text
    caption: str = ""


class SeenMessages:
    """Meta may deliver the same webhook more than once; remembers recent message IDs."""

    def __init__(self, limit: int = 2000):
        self._ids: OrderedDict[str, None] = OrderedDict()
        self._limit = limit
        self._lock = threading.Lock()

    def first_time(self, mid: str) -> bool:
        with self._lock:
            if mid in self._ids:
                return False
            self._ids[mid] = None
            if len(self._ids) > self._limit:
                self._ids.popitem(last=False)
            return True


def reel_request(message: dict) -> tuple[str | None, str]:
    """(video URL, caption) that a DM asks to post; (None, "") if it contains no reel.

    Text sent together with a reel link becomes the caption.
    """
    text = message.get("text") or ""
    url = find_instagram_url(text)
    if url:
        return url, text.replace(url, "").strip()
    for attachment in message.get("attachments") or []:
        payload_url = (attachment.get("payload") or {}).get("url")
        if attachment.get("type") in VIDEO_ATTACHMENT_TYPES and payload_url:
            # A shared reel may arrive as an instagram.com link or as a direct video URL.
            return find_instagram_url(payload_url) or payload_url, ""
    return None, ""


def iter_jobs(payload: dict, accounts: Mapping[str, Account], seen: SeenMessages,
              accounts_file: str = "accounts.toml") -> Iterator[Job]:
    """A Job for each new DM in the payload that an allowed sender sent to an enabled account.

    accounts maps Instagram account IDs to accounts; accounts_file is only used in log messages.
    """
    if payload.get("object") != "instagram":
        return
    for entry in payload.get("entry", []):
        ig_id = str(entry.get("id") or "")  # the Instagram account that received the DM
        account = accounts.get(ig_id)
        for event in entry.get("messaging", []):
            message = event.get("message") or {}
            sender_id = (event.get("sender") or {}).get("id")
            if not message or not sender_id or message.get("is_echo") or message.get("is_deleted"):
                continue  # read receipts, reactions, our own replies, deletions
            if message.get("mid") and not seen.first_time(message["mid"]):
                continue
            if account is None:
                logger.warning("DM to Instagram account %s, which is not in %s (sender %s). "
                               "Add the account there to use it.", ig_id, accounts_file, sender_id)
                continue
            if not account.enabled:
                logger.info("[%s] Ignoring DM: account is disabled in %s.", account.name, accounts_file)
                continue
            if not account.allows(sender_id):
                # Sender IDs are per account: the same person has a different ID on each account.
                logger.warning("Ignoring DM to [%s] from sender %s. To allow it, add the ID to "
                               "allowed_senders for this account in %s.", account.name, sender_id,
                               accounts_file)
                continue
            url, caption = reel_request(message)
            yield Job(account, sender_id, url, caption)
