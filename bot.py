"""VPKN Telegram assistant bot entrypoint.

Two run modes:

* **Polling** (default for local dev): just runs `bot.py`. No public URL needed.
* **Webhook** (production on free PaaS): set `WEBHOOK_BASE_URL` and `PORT` in
  the environment and the bot will register a Telegram webhook against
  `${WEBHOOK_BASE_URL}/telegram/${WEBHOOK_SECRET}` and listen on `0.0.0.0:$PORT`.
"""
from __future__ import annotations

import logging
import os
import secrets

from telegram.ext import Application

from app.ai import AI
from app.config import Config
from app.handlers import register
from app.storage import Storage


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
        webhook_secret = config.webhook_secret or secrets.token_urlsafe(24)
        url_path = f"telegram/{webhook_secret}"
        webhook_url = f"{config.webhook_base_url}/{url_path}"
        logging.info("Starting webhook at %s (port %s)", webhook_url, config.port)
        application.run_webhook(
            listen="0.0.0.0",
            port=config.port,
            url_path=url_path,
            webhook_url=webhook_url,
            secret_token=webhook_secret if webhook_secret.isalnum() else None,
            allowed_updates=None,
        )
    else:
        logging.info("Starting long-polling mode")
        application.run_polling(allowed_updates=None, drop_pending_updates=True)


if __name__ == "__main__":
    main()
