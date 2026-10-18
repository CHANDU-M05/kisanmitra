"""
telegram_bot/messaging.py — Markdown-safe send helpers.

Telegram rejects (HTTP 400) any message whose parse_mode="Markdown" entities
are unbalanced. LLM advisory text and backend-formatted strings routinely
contain stray '*' or '_' characters — historically this made the update crash
inside the handler and the farmer received NO reply at all for a question the
backend had answered correctly.

These helpers send dynamically-generated text as Markdown first and fall back
to a plain-text rendering on any Telegram API error, so a reply ALWAYS lands.
"""
from __future__ import annotations

import logging

from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

logger = logging.getLogger("kisanmitra.telegram.messaging")


def _strip_markdown(text: str) -> str:
    """Best-effort plain rendering: drop emphasis markers, keep all content."""
    return (
        text.replace("**", "").replace("__", "")
            .replace("*", "").replace("`", "")
    )


async def answer_safe(message: Message, text: str, reply_markup=None) -> None:
    """message.answer with Markdown, guaranteed plain-text fallback."""
    try:
        await message.answer(text, parse_mode="Markdown", reply_markup=reply_markup)
    except TelegramAPIError as exc:
        logger.warning("Markdown send failed (%s) — resending as plain text.", exc)
        await message.answer(_strip_markdown(text), reply_markup=reply_markup)


async def edit_safe(message: Message, text: str, reply_markup=None) -> None:
    """message.edit_text with Markdown, guaranteed plain-text fallback."""
    try:
        await message.edit_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    except TelegramAPIError as exc:
        logger.warning("Markdown edit failed (%s) — re-editing as plain text.", exc)
        await message.edit_text(_strip_markdown(text), reply_markup=reply_markup)
