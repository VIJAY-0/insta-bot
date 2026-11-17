"""Startup checks: log whether each account and the server settings are ready to use."""

import logging
import threading
import time
from collections.abc import Iterable

import requests

from .accounts import Account
from .config import Settings
from .instagram import InstagramError

logger = logging.getLogger(__name__)


def run_startup_checks(settings: Settings, accounts: Iterable[Account]) -> None:
    for account in accounts:
        check_account(account)

    if not settings.verify_token:
        logger.warning("VERIFY_TOKEN is not set: Meta can't verify the webhook.")
    if not settings.app_secret:
        logger.warning("APP_SECRET is not set: webhook signatures are not verified.")
    if not settings.public_url:
        logger.warning("PUBLIC_URL is not set: publishing will not work.")
    else:
        threading.Thread(target=check_public_url, args=(settings.public_url,), daemon=True).start()


def check_account(account: Account) -> None:
    """Confirm the account's token works and it may publish; warn about risky sender settings."""
    if not account.enabled:
        logger.info("[%s] Disabled.", account.name)
        return
    try:
        username = account.api.username(account.ig_id)
        limit = account.api.publishing_limit(account.ig_id)
        logger.info("[%s] OK: @%s (%s), can publish (%s of %s posts used in 24h)%s.",
                    account.name, username, account.ig_id, limit.get("quota_usage", "?"),
                    (limit.get("config") or {}).get("quota_total", "?"),
                    ", DRY RUN" if account.dry_run else "")
    except InstagramError as e:
        logger.error("[%s] Its access_token can't use account %s: %s", account.name, account.ig_id, e)

    if not account.allowed_senders:
        logger.warning("[%s] allowed_senders is empty, so its DMs are ignored. DM the account; "
                       "the log shows the sender ID to add.", account.name)
    elif "*" in account.allowed_senders:
        logger.warning('[%s] allowed_senders is ["*"]: ANYONE can get reels posted.', account.name)


def check_public_url(public_url: str, delay: float = 3) -> None:
    """Confirm PUBLIC_URL reaches this app. Waits first so the server has time to start."""
    time.sleep(delay)
    try:
        resp = requests.get(f"{public_url}/", timeout=15)
        ok = (resp.ok and resp.headers.get("Content-Type", "").startswith("application/json")
              and resp.json().get("status") == "ok")
    except (requests.RequestException, ValueError) as e:
        logger.error("PUBLIC_URL %s is not reachable: %s", public_url, e)
        return
    if ok:
        logger.info("PUBLIC_URL %s reaches this app.", public_url)
    else:
        logger.error("PUBLIC_URL %s answered, but not from this app (HTTP %s).", public_url, resp.status_code)
