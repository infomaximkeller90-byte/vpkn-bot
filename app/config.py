"""Centralized config loaded from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Load .env.local first (developer override), then .env if present.
for candidate in (".env.local", ".env"):
    if os.path.exists(candidate):
        load_dotenv(candidate, override=False)


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Set it in your environment or in a .env file."
        )
    return value


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    gemini_api_key: str
    gemini_model: str
    gemini_image_model: str
    webhook_base_url: str
    webhook_secret: str
    port: int
    data_dir: str

    @classmethod
    def from_env(cls) -> "Config":
        data_dir = os.environ.get("DATA_DIR", "bot_data").strip() or "bot_data"
        os.makedirs(data_dir, exist_ok=True)

        # On Render the platform sets RENDER_EXTERNAL_HOSTNAME automatically.
        webhook_base_url = os.environ.get("WEBHOOK_BASE_URL", "").strip().rstrip("/")
        if not webhook_base_url:
            render_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
            if render_host:
                webhook_base_url = f"https://{render_host}"

        return cls(
            telegram_bot_token=_require("TELEGRAM_BOT_TOKEN"),
            gemini_api_key=_require("GEMINI_API_KEY"),
            gemini_model=os.environ.get("GEMINI_MODEL", "gemini-flash-latest").strip()
            or "gemini-flash-latest",
            gemini_image_model=os.environ.get(
                "GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image"
            ).strip()
            or "gemini-2.5-flash-image",
            webhook_base_url=webhook_base_url,
            webhook_secret=os.environ.get("WEBHOOK_SECRET", "").strip(),
            port=int(os.environ.get("PORT", "8080").strip() or "8080"),
            data_dir=data_dir,
        )
