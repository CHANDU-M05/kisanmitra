"""
telegram_bot/config.py — Bot configuration loaded from environment / .env

Reads from the same root-level .env used by the FastAPI backend, so you
only maintain one secrets file.
"""
from __future__ import annotations
import os
from pathlib import Path

from dotenv import load_dotenv

# Load the project-root .env (two levels up from this file)
_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(_ENV_FILE, override=False)


def _require(key: str) -> str:
    val = os.getenv(key, "").strip()
    if not val:
        raise EnvironmentError(
            f"Required env var {key!r} is not set. "
            f"Add it to your .env file:\n  {key}=<value>"
        )
    return val


# Telegram Bot token from @BotFather
TELEGRAM_BOT_TOKEN: str = _require("TELEGRAM_BOT_TOKEN")

# Redis URL for FSM state persistence (survives restarts)
# Default: local Redis, DB 1 (DB 0 is used by the main app if any)
REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/1")

# KisanMitra FastAPI backend URL — the bot ONLY calls this, never imports ML code.
BACKEND_URL: str = os.getenv("BACKEND_URL", "http://localhost:8000")

# Timeout for backend HTTP calls (seconds)
BACKEND_TIMEOUT: float = float(os.getenv("BACKEND_TIMEOUT", "45.0"))

# Webhook mode vs long-polling. Set TELEGRAM_WEBHOOK_URL in production.
WEBHOOK_URL: str = os.getenv("TELEGRAM_WEBHOOK_URL", "")
WEBHOOK_SECRET: str = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")

# Shared internal secret for bot-to-backend API authentication
INTERNAL_SECRET: str = os.getenv("SECRET_KEY", "REDACTED_IN_HISTORY")
