"""
telegram_bot/handlers/freetext.py — Catch-all free-text handler.

Registered LAST in the dispatcher (after all flow-specific routers).
Handles natural language input in ANY state — the FSM state is cleared
so a free-text message always gets a clean, direct response.

This is the piece that makes buttons and typing coexist cleanly:
  - Buttons build a query and call the engine via the flow handlers.
  - Free text goes straight to the engine's NLP — same backend call, same result shape.
  - Both land on format_result() for rendering.
"""
from __future__ import annotations

import logging

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from telegram_bot.backend_client import send_to_engine
from telegram_bot.formatters import format_result
from telegram_bot.keyboards import (
    advisory_followup_keyboard,
    anomaly_keyboard,
    declaration_confirm_keyboard,
    main_menu_keyboard,
    result_keyboard,
)

router = Router()
logger = logging.getLogger("kisanmitra.telegram.freetext")


def _keyboard_for(result: dict):
    t = result.get("type", "error")
    if t == "declaration_prompt":
        return declaration_confirm_keyboard(
            crop=result.get("crop", "Tomato"),
            district=result.get("district", "Kolar"),
            area=result.get("area", 1.0),
        )
    if t in ("forecast", "saturation", "declaration"):
        return result_keyboard()
    if t == "anomaly_flagged":
        return anomaly_keyboard()
    if t == "advisory":
        return advisory_followup_keyboard()
    return main_menu_keyboard()


@router.message()
async def handle_free_text(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        return

    # If the user was mid-flow and typed something unexpected, clear the stale state.
    current_state = await state.get_state()
    if current_state:
        logger.debug(
            "Free-text received while in state=%s — clearing FSM and handling via NLP.",
            current_state,
        )
        await state.clear()

    result = await send_to_engine(
        sender_id=str(message.from_user.id),
        text=text,
    )

    await message.answer(
        format_result(result),
        parse_mode="Markdown",
        reply_markup=_keyboard_for(result),
    )
