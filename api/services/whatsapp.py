"""
api/services/whatsapp.py — GUARDRAIL 4

All outgoing WhatsApp messages flow through this module.
Handles Meta API edge cases without crashing the server:
  - 403 Forbidden  → sandbox / unverified number (log + continue)
  - 429 Too Many   → rate-limit (log + continue)
  - Network errors → log + continue
"""
from __future__ import annotations

import logging
from enum import Enum

import requests

from api.core.config import settings

logger = logging.getLogger("kisanmitra.whatsapp")

_GRAPH_URL = "https://graph.facebook.com/v19.0"


class SendResult(str, Enum):
    OK         = "ok"
    DEV_MODE   = "dev_mode"      # No token configured
    FORBIDDEN  = "forbidden"     # 403 — unverified sandbox number
    RATE_LIMIT = "rate_limit"    # 429
    ERROR      = "error"         # Other HTTP or network error


def send_message(phone: str, text: str) -> SendResult:
    """
    Send a WhatsApp text message via Meta Cloud API.

    GUARDRAIL 4: Never raises. Returns a SendResult enum so callers
    can log outcomes without crashing the FastAPI request cycle.
    """
    token    = settings.whatsapp_token
    phone_id = settings.whatsapp_phone_number_id

    # ── Dev / sandbox mode ────────────────────────────────
    if not token or token == "fill_this_later":
        logger.info("[WA DEV] → %s | %s", phone, text[:100])
        return SendResult.DEV_MODE

    try:
        resp = requests.post(
            f"{_GRAPH_URL}/{phone_id}/messages",
            json={
                "messaging_product": "whatsapp",
                "to": phone,
                "type": "text",
                "text": {"body": text},
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )

        # GUARDRAIL 4: explicit status-code handling
        if resp.status_code == 200:
            logger.debug("[WA OK] → %s", phone)
            return SendResult.OK

        if resp.status_code == 403:
            # Meta returns 403 for unverified sandbox numbers.
            # Log clearly; do NOT raise so the webhook still returns 200.
            logger.warning(
                "[WA 403 FORBIDDEN] Phone %s is not an approved test number. "
                "Add it at developers.facebook.com → WhatsApp → Test numbers. "
                "Raw: %s",
                phone,
                resp.text[:200],
            )
            return SendResult.FORBIDDEN

        if resp.status_code == 429:
            logger.warning("[WA 429 RATE-LIMIT] → %s — back off.", phone)
            return SendResult.RATE_LIMIT

        logger.error("[WA HTTP %s] → %s | %s", resp.status_code, phone, resp.text[:200])
        return SendResult.ERROR

    except requests.Timeout:
        logger.error("[WA TIMEOUT] → %s — Meta API did not respond in 10s.", phone)
        return SendResult.ERROR

    except requests.RequestException as exc:
        logger.error("[WA NETWORK ERROR] → %s | %s", phone, exc)
        return SendResult.ERROR


def send_feedback_buttons(phone: str, text: str) -> SendResult:
    """
    Send an interactive button message asking for feedback.
    """
    token    = settings.whatsapp_token
    phone_id = settings.whatsapp_phone_number_id

    if not token or token == "fill_this_later":
        logger.info("[WA DEV FEEDBACK] → %s | %s", phone, text[:100])
        return SendResult.DEV_MODE

    try:
        resp = requests.post(
            f"{_GRAPH_URL}/{phone_id}/messages",
            json={
                "messaging_product": "whatsapp",
                "to": phone,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": text},
                    "action": {
                        "buttons": [
                            {
                                "type": "reply",
                                "reply": {"id": "feedback_positive", "title": "👍 Yes"}
                            },
                            {
                                "type": "reply",
                                "reply": {"id": "feedback_negative", "title": "👎 No"}
                            }
                        ]
                    }
                }
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        return SendResult.OK if resp.status_code == 200 else SendResult.ERROR
    except Exception as exc:
        logger.error("[WA FEEDBACK ERROR] → %s | %s", phone, exc)
        return SendResult.ERROR
