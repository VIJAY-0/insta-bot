"""Server-wide settings, read from .env. Per-account settings live in accounts.toml (accounts.py)."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    public_url: str = ""  # public HTTPS address that reaches this app, no trailing slash
    app_secret: str = ""  # Meta app secret; "" = don't verify webhook signatures
    verify_token: str = ""  # must match "Verify token" in the Meta webhook settings
    dry_run: bool = False  # default for accounts that don't set dry_run themselves
    port: int = 5000
    graph_api_version: str = "v27.0"
    cookies_file: str | None = None  # Netscape cookies.txt, lets yt-dlp download as a logged-in user
    accounts_file: Path = PROJECT_DIR / "accounts.toml"
    download_dir: Path = PROJECT_DIR / "downloads"

    @classmethod
    def from_env(cls, project_dir: Path = PROJECT_DIR) -> "Settings":
        load_dotenv(project_dir / ".env")
        return cls(
            public_url=_env("PUBLIC_URL").rstrip("/"),
            app_secret=_env("APP_SECRET"),
            verify_token=_env("VERIFY_TOKEN"),
            dry_run=_env("DRY_RUN", "false").lower() in ("1", "true", "yes"),
            port=int(_env("PORT", "5000")),
            graph_api_version=_env("GRAPH_API_VERSION", "v27.0"),
            cookies_file=_env("INSTAGRAM_COOKIES_FILE") or None,
            accounts_file=project_dir / _env("ACCOUNTS_FILE", "accounts.toml"),
            download_dir=project_dir / "downloads",
        )


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()
