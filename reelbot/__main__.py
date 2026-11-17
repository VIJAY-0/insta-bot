"""Run the bot:  python -m reelbot"""

import logging
import sys

from flask import Flask

from .accounts import AccountStore, ConfigError
from .bot import ReelBot
from .checks import run_startup_checks
from .config import Settings
from .server import create_app

logger = logging.getLogger("reelbot")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings.from_env()
    accounts = AccountStore(settings.accounts_file, settings.graph_api_version, settings.dry_run)
    try:
        loaded = accounts.get()
    except ConfigError as e:
        logger.error("%s", e)
        return 1

    bot = ReelBot(settings, accounts)
    bot.start_worker()
    run_startup_checks(settings, loaded.values())
    serve(create_app(bot), settings.port)
    return 0


def serve(app: Flask, port: int) -> None:
    """Serve with waitress if it's installed, otherwise with Flask's development server."""
    try:
        import waitress
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
    else:
        logger.info("Listening on http://0.0.0.0:%s", port)
        waitress.serve(app, host="0.0.0.0", port=port, threads=8)


if __name__ == "__main__":
    sys.exit(main())
