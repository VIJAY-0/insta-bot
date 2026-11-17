"""The Instagram accounts the bot serves, loaded from accounts.toml (see accounts.example.toml)."""

import logging
import threading
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .instagram import InstagramAPI

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """accounts.toml is missing or invalid."""


@dataclass
class Account:
    name: str  # label from [accounts.<name>], used in logs
    ig_id: str  # Instagram professional account ID (1784...)
    api: InstagramAPI = field(repr=False)
    allowed_senders: set[str]
    enabled: bool = True
    dry_run: bool = False  # download and reply, but don't publish

    def allows(self, sender_id: str) -> bool:
        return "*" in self.allowed_senders or sender_id in self.allowed_senders


def load_accounts(path: Path, api_version: str, default_dry_run: bool = False) -> dict[str, Account]:
    """Parse and validate the accounts file. Returns {ig_account_id: Account}.

    default_dry_run applies to accounts that don't set dry_run themselves (DRY_RUN in .env).
    """
    if not path.exists():
        raise ConfigError(f"{path.name} not found. Copy accounts.example.toml to {path.name} and fill it in.")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path.name} is not valid TOML: {e}") from None

    accounts: dict[str, Account] = {}
    for name, cfg in (data.get("accounts") or {}).items():
        where = f"{path.name} [accounts.{name}]"
        account = _parse_account(name, cfg, where, api_version, default_dry_run)
        if account.ig_id in accounts:
            raise ConfigError(f"{where}: ig_account_id {account.ig_id} is already used by "
                              f"[accounts.{accounts[account.ig_id].name}].")
        accounts[account.ig_id] = account
    if not accounts:
        raise ConfigError(f"{path.name} has no [accounts.<name>] sections.")
    return accounts


def _parse_account(name: str, cfg: object, where: str, api_version: str, default_dry_run: bool) -> Account:
    if not isinstance(cfg, dict):
        raise ConfigError(f"{where}: expected a section of settings, e.g. [accounts.{name}].")
    ig_id = str(cfg.get("ig_account_id", "")).strip()
    token = str(cfg.get("access_token", "")).strip()
    senders = cfg.get("allowed_senders", [])
    enabled = cfg.get("enabled", True)
    dry_run = cfg.get("dry_run", default_dry_run)

    if not ig_id.isdigit():
        raise ConfigError(f"{where}: ig_account_id must be the numeric Instagram account ID.")
    if not token:
        raise ConfigError(f"{where}: access_token is missing.")
    if not isinstance(senders, list):
        raise ConfigError(f'{where}: allowed_senders must be a list, e.g. ["123", "456"].')
    for key, value in (("enabled", enabled), ("dry_run", dry_run)):
        if not isinstance(value, bool):
            raise ConfigError(f"{where}: {key} must be true or false (without quotes).")

    return Account(
        name=name,
        ig_id=ig_id,
        api=InstagramAPI(token, api_version),
        allowed_senders={str(s).strip() for s in senders if str(s).strip()},
        enabled=enabled,
        dry_run=dry_run,
    )


class AccountStore:
    """Holds the loaded accounts and reloads them when the file changes, so edits need no restart."""

    def __init__(self, path: Path, api_version: str, default_dry_run: bool = False):
        self.path = path
        self.api_version = api_version
        self.default_dry_run = default_dry_run
        self._accounts: dict[str, Account] | None = None
        self._mtime: float | None = None
        self._lock = threading.Lock()

    def get(self) -> dict[str, Account]:
        """The current accounts, by Instagram account ID.

        Raises ConfigError only on the first load; after that, a bad edit is logged and the
        previous accounts are kept.
        """
        with self._lock:
            mtime = self.path.stat().st_mtime if self.path.exists() else None
            if self._accounts is None:
                self._accounts = self._load()
            elif mtime != self._mtime:
                try:
                    self._accounts = self._load()
                    logger.info("Reloaded %s (%d accounts).", self.path.name, len(self._accounts))
                except ConfigError as e:
                    logger.error("%s Keeping the previous accounts.", e)
            self._mtime = mtime
            return self._accounts

    def _load(self) -> dict[str, Account]:
        return load_accounts(self.path, self.api_version, self.default_dry_run)
