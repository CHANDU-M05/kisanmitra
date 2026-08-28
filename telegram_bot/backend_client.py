"""
telegram_bot/backend_client.py — HTTP client for the KisanMitra FastAPI backend.

The bot process NEVER imports backend Python modules directly.
All domain logic (NLP, ML, RAG) lives in the FastAPI process.
This client is the only coupling point.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from telegram_bot.config import BACKEND_URL, BACKEND_TIMEOUT

logger = logging.getLogger("kisanmitra.telegram.client")

_FALLBACK_RESULT = {
    "type": "error",
    "detail": "KisanMitra service is slow right now. Please try again in a moment. 🙏",
}


async def send_to_engine(
    sender_id: str,
    text: str,
    channel: str = "telegram",
    crop: Optional[str] = None,
    district: Optional[str] = None,
    area: Optional[float] = None,
    intent: Optional[str] = None,
    farmer_name: Optional[str] = None,
) -> dict:
    """
    POST /api/v1/conversation/message and return the structured result dict.

    On timeout or 5xx the bot receives a friendly fallback rather than
    an unhandled exception reaching the farmer.

    `crop`, `district`, `area` are pre-resolved entities from button flows.
    `intent` is the explicit Intent enum name ("PRICE_QUERY" etc.) — when set,
    the backend skips NLP classification entirely.
    `farmer_name` is the actual profile name of the farmer from Telegram/WhatsApp.
    """
    payload: dict = {
        "sender_id": sender_id,
        "text": text,
        "channel": channel,
    }
    if crop:
        payload["crop"] = crop
    if district:
        payload["district"] = district
    if area is not None:
        payload["area"] = area
    if intent:
        payload["intent"] = intent
    if farmer_name:
        payload["farmer_name"] = farmer_name

    try:
        async with httpx.AsyncClient(timeout=BACKEND_TIMEOUT) as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/v1/conversation/message",
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.TimeoutException:
        logger.warning("Backend timeout for sender=%s text=%r", sender_id, text[:60])
        return _FALLBACK_RESULT
    except httpx.HTTPStatusError as exc:
        logger.error(
            "Backend HTTP error %s for sender=%s: %s",
            exc.response.status_code, sender_id, exc.response.text[:200],
        )
        return _FALLBACK_RESULT
    except Exception as exc:
        logger.exception("Unexpected backend error for sender=%s: %s", sender_id, exc)
        return _FALLBACK_RESULT
