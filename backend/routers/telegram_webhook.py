"""
backend/routers/telegram_webhook.py — Production Telegram Webhook Router

Mounts a secure webhook endpoint for Telegram updates within the FastAPI process.
This resolves the Render free-tier hosting constraint by eliminating the need
for a separate persistent background polling worker.

Architecture:
1. Telegram sends POST /api/v1/webhook/telegram with update JSON.
2. Verified against X-Telegram-Bot-Api-Secret-Token (constant-time comparison).
3. If unconfigured, the endpoint returns 404 (optional channel design).
4. Valid updates are parsed and dispatched to the aiogram Dispatcher with existing routers.
5. Exceptions are captured and isolated; secrets are never leaked.
"""
from __future__ import annotations

import logging
import secrets
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel

from backend.core.config import settings

logger = logging.getLogger("kisanmitra.telegram.webhook")

router = APIRouter(prefix="/webhook/telegram", tags=["telegram-webhook"])

_bot_instance = None
_dp_instance = None


async def close_telegram_components() -> None:
    """Closes the active Bot session gracefully during application shutdown."""
    global _bot_instance, _dp_instance
    if _bot_instance is not None:
        try:
            if hasattr(_bot_instance, "session") and _bot_instance.session:
                await _bot_instance.session.close()
                logger.info("Telegram Bot HTTP session closed successfully.")
        except Exception as e:
            logger.warning(f"Error closing Telegram Bot session on shutdown: {e}")
        finally:
            _bot_instance = None
            _dp_instance = None


def get_telegram_components():
    """Lazily initialize and cache the aiogram Bot and Dispatcher."""
    global _bot_instance, _dp_instance
    if _dp_instance is not None:
        return _bot_instance, _dp_instance

    token = settings.telegram_bot_token.get_secret_value()
    if not token:
        return None, None

    try:
        from aiogram import Bot, Dispatcher
        from aiogram.client.default import DefaultBotProperties
        from aiogram.enums import ParseMode
        from aiogram.fsm.storage.memory import MemoryStorage

        from telegram_bot.handlers import (
            advisory,
            declare,
            freetext,
            mycrops,
            price,
            saturation,
            start,
        )

        bot = Bot(
            token=token,
            default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
        )
        storage = MemoryStorage()
        dp = Dispatcher(storage=storage)

        # Register existing routers in exact priority order
        dp.include_router(start.router)
        dp.include_router(price.router)
        dp.include_router(saturation.router)
        dp.include_router(declare.router)
        dp.include_router(advisory.router)
        dp.include_router(mycrops.router)
        dp.include_router(freetext.router)

        _bot_instance = bot
        _dp_instance = dp
        logger.info("Telegram aiogram Dispatcher initialized for webhook mode.")
        return _bot_instance, _dp_instance
    except Exception as e:
        logger.error(f"Failed to initialize Telegram webhook components: {e}")
        return None, None


def _refuse_if_unconfigured() -> str:
    """Telegram webhook is optional. Returns the secret token if configured."""
    token = settings.telegram_bot_token.get_secret_value()
    expected_secret = settings.telegram_webhook_secret

    if not token:
        raise HTTPException(status_code=404, detail="Telegram integration is not configured.")

    return expected_secret


@router.post("")
async def handle_telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(None, alias="X-Telegram-Bot-Api-Secret-Token"),
) -> dict:
    """
    Receives and processes incoming Telegram updates via HTTPS webhook.

    HTTP Response Semantics:
    - 404: Telegram integration unconfigured.
    - 403: Missing or invalid X-Telegram-Bot-Api-Secret-Token header.
    - 400: Malformed JSON or non-dict update missing `update_id`.
    - 503: Bot/Dispatcher components unavailable (transient startup/configuration issue).
    - 500: Temporary backend processing failure during update execution. Returns HTTP 500
           so Telegram Bot API can retry delivery according to its exponential backoff policy.
    - 200: Successfully validated and processed update.
    """
    expected_secret = _refuse_if_unconfigured()

    # Verify secret token if configured
    if expected_secret:
        if not x_telegram_bot_api_secret_token or not secrets.compare_digest(
            x_telegram_bot_api_secret_token.encode("utf-8"),
            expected_secret.encode("utf-8"),
        ):
            logger.warning("Rejected Telegram webhook update: invalid or missing secret token.")
            raise HTTPException(status_code=403, detail="Invalid webhook secret token.")

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

    if not isinstance(data, dict) or "update_id" not in data:
        raise HTTPException(status_code=400, detail="Malformed Telegram update.")

    bot, dp = get_telegram_components()
    if bot is None or dp is None:
        raise HTTPException(status_code=503, detail="Telegram bot service unavailable.")

    from aiogram.types import Update

    try:
        update = Update.model_validate(data, context={"bot": bot})
        await dp.feed_update(bot=bot, update=update)
        return {"ok": True}
    except Exception as e:
        logger.exception("Error processing Telegram update in webhook dispatcher.")
        # Return HTTP 500 so Telegram will retry transient failures, rather than silently dropping
        raise HTTPException(status_code=500, detail="Internal processing error.")
