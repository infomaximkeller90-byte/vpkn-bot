"""VPKN Telegram assistant bot entrypoint.

Two run modes:

* **Polling** (default for local dev): just runs `bot.py`. No public URL needed.
* **Webhook** (production on free PaaS): set `WEBHOOK_BASE_URL` and `PORT` in
  the environment and the bot will register a Telegram webhook against
  ``${WEBHOOK_BASE_URL}/telegram/${url_token}`` and listen on ``0.0.0.0:$PORT``.
"""
from __future__ import annotations

import logging
import os
import re
import secrets

from telegram.ext import Application

from app.ai import AI
from app.config import Config
from app.handlers import register
from app.storage import Storage


# Telegram's X-Telegram-Bot-Api-Secret-Token header (and the URL path component
# we use to receive webhooks) must only contain these characters.
_URL_SAFE_RE = re.compile(r"[^A-Za-z0-9_-]")


def _sanitize_secret(value: str) -> str:
    """Coerce an arbitrary secret into URL-safe base64url-compatible chars."""
    # Standard base64 (the format Render's `generateValue: true` produces)
    # contains `+`, `/`, and `=` which break both URL paths and Telegram's
    # secret_token validation. Map them to the base64url equivalents and drop
    # everything else just to be safe.
    converted = value.replace("+", "-").replace("/", "_").rstrip("=")
    return _URL_SAFE_RE.sub("", converted)


def _setup_logging() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    # PTB & httpx are very chatty at INFO.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram.ext.Application").setLevel(logging.WARNING)


def build_app(config: Config) -> Application:
    application = Application.builder().token(config.telegram_bot_token).build()
    ai = AI(
        api_key=config.gemini_api_key,
        chat_model=config.gemini_model,
        image_model=config.gemini_image_model,
    )
    storage = Storage(config.data_dir)
    register(application, ai, storage)
    return application


def main() -> None:
    _setup_logging()
    config = Config.from_env()
    application = build_app(config)

    if config.webhook_base_url:
        raw_secret = config.webhook_secret or secrets.token_urlsafe(24)
        url_token = _sanitize_secret(raw_secret)
        if len(url_token) < 16:
            # Fall back to a freshly generated, guaranteed-safe token if the
            # provided secret was empty or stripped down to almost nothing.
            url_token = _sanitize_secret(secrets.token_urlsafe(32))
        url_path = f"telegram/{url_token}"
        webhook_url = f"{config.webhook_base_url}/{url_path}"
        logging.info("Starting webhook at %s (port %s)", webhook_url, config.port)
        application.run_webhook(
            listen="0.0.0.0",
            port=config.port,
            url_path=url_path,
            webhook_url=webhook_url,
            secret_token=url_token,
            allowed_updates=None,
            drop_pending_updates=True,
        )
    else:
        logging.info("Starting long-polling mode")
        application.run_polling(allowed_updates=None, drop_pending_updates=True)


if __name__ == "__main__":
    main()
