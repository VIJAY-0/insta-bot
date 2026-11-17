"""Instagram accounts the bot serves, loaded from accounts.toml (see accounts.example.toml)."""

import logging
import threading
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from instagram_api import InstagramAPI

logger = logging.getLogger("reel-bot")


class ConfigError(Exception):
    pass


@dataclass
class Account:
    name: str  # label from [accounts.<name>], used in logs
    ig_id: str
    api: InstagramAPI = field(repr=False)
    allowed_senders: set[str]
    enabled: bool = True
    dry_run: bool | None = None  # None: use DRY_RUN from .env

    def allows(self, sender_id: str) -> bool:
        return "*" in self.allowed_senders or sender_id in self.allowed_senders


def load_accounts(path: Path, api_version: str) -> dict[str, Account]:
    """Parse and validate the accounts file. Returns {ig_account_id: Account}."""
    if not path.exists():
        raise ConfigError(f"{path.name} not found. Copy accounts.example.toml to {path.name} and fill it in.")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path.name} is not valid TOML: {e}") from None

    accounts: dict[str, Account] = {}
    for name, cfg in (data.get("accounts") or {}).items():
        where = f"{path.name} [accounts.{name}]"
        ig_id = str(cfg.get("ig_account_id", "")).strip()
        token = str(cfg.get("access_token", "")).strip()
        senders = cfg.get("allowed_senders", [])
        if not ig_id.isdigit():
            raise ConfigError(f"{where}: ig_account_id must be the numeric Instagram account ID.")
        if not token:
            raise ConfigError(f"{where}: access_token is missing.")
        if ig_id in accounts:
            raise ConfigError(f"{where}: ig_account_id {ig_id} is already used by [accounts.{accounts[ig_id].name}].")
        if not isinstance(senders, list):
            raise ConfigError(f'{where}: allowed_senders must be a list, e.g. ["123", "456"].')
        dry_run = cfg.get("dry_run")
        accounts[ig_id] = Account(
            name=name,
            ig_id=ig_id,
            api=InstagramAPI(token, api_version),
            allowed_senders={str(s).strip() for s in senders if str(s).strip()},
            enabled=bool(cfg.get("enabled", True)),
            dry_run=None if dry_run is None else bool(dry_run),
        )
    if not accounts:
        raise ConfigError(f"{path.name} has no [accounts.<name>] sections.")
    return accounts


class AccountStore:
    """Holds the loaded accounts and reloads them when the file changes, so edits need no restart."""

    def __init__(self, path: Path, api_version: str):
        self.path = path
        self.api_version = api_version
        self._accounts: dict[str, Account] = {}
        self._mtime: float | None = None
        self._loaded = False
        self._lock = threading.Lock()

    def get(self) -> dict[str, Account]:
        """Raises ConfigError only on the first load; later bad edits keep the previous accounts."""
        with self._lock:
            mtime = self.path.stat().st_mtime if self.path.exists() else None
            if not self._loaded:
                self._accounts = load_accounts(self.path, self.api_version)
                self._loaded = True
            elif mtime != self._mtime:
                try:
                    self._accounts = load_accounts(self.path, self.api_version)
                    logger.info("Reloaded %s (%d accounts).", self.path.name, len(self._accounts))
                except ConfigError as e:
                    logger.error("%s Keeping the previous accounts.", e)
            self._mtime = mtime
            return self._accounts
