"""
telegram_bot/handlers/advisory.py — Agronomy Q&A flow.

State machine: menu:advisory → AdvisoryFlow.awaiting_question → result

Free-text only; the farmer types a question and it goes straight to the RAG pipeline.
Feedback (👍/👎) is persisted to the backend via POST /farmer/advisory/feedback.
"""
from __future__ import annotations

import logging

import httpx
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from telegram_bot.backend_client import send_to_engine
from telegram_bot.config import BACKEND_URL, BACKEND_TIMEOUT
from telegram_bot.formatters import format_result
from telegram_bot.keyboards import advisory_followup_keyboard, main_menu_keyboard
from telegram_bot.states import AdvisoryFlow

router = Router()
logger = logging.getLogger("kisanmitra.telegram.advisory")


@router.callback_query(F.data == "menu:advisory")
async def start_advisory_flow(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdvisoryFlow.awaiting_question)
    await cb.message.edit_text(
        "💬 *Agronomy Advice*\n\n"
        "Ask me anything about your crops:\n"
        "• Disease & pest management\n"
        "• Fertilizer & soil health\n"
        "• Irrigation & sowing tips\n\n"
        "_Type your question in English or Kannada:_",
        parse_mode="Markdown",
    )
    await cb.answer()


@router.message(AdvisoryFlow.awaiting_question)
async def advisory_question_received(message: Message, state: FSMContext) -> None:
    await message.answer("⏳ Consulting our agronomy database…")

    result = await send_to_engine(
        sender_id=str(message.from_user.id),
        text=message.text or "",
    )

    # Store the backend-assigned message_id for feedback persistence.
    # The /api/v1/conversation/message response doesn't return a message_id,
    # but /farmer/advisory endpoint does. We use the channel-agnostic endpoint
    # which writes ChatHistory — we read back the id from the result if present.
    advisory_msg_id = result.get("id") or result.get("message_id")
    if advisory_msg_id:
        await state.update_data(last_advisory_id=str(advisory_msg_id))

    await message.answer(
        format_result(result),
        parse_mode="Markdown",
        reply_markup=advisory_followup_keyboard(),
    )
    await state.clear()
    # Re-store the id AFTER clear so it survives for the feedback callback.
    if advisory_msg_id:
        await state.update_data(last_advisory_id=str(advisory_msg_id))


@router.callback_query(F.data.startswith("feedback:"))
async def advisory_feedback(cb: CallbackQuery, state: FSMContext) -> None:
    sentiment = cb.data.split(":")[1]
    score     = 1 if sentiment == "positive" else -1

    if sentiment == "positive":
        ack = "👍 Thank you! Glad that was helpful. — KisanMitra 🌾"
    else:
        ack = "👎 Thanks for the feedback. We'll use this to improve. — KisanMitra 🌾"

    # Persist feedback score to backend if we have a message_id.
    data             = await state.get_data()
    advisory_msg_id  = data.get("last_advisory_id")
    if advisory_msg_id:
        try:
            async with httpx.AsyncClient(timeout=BACKEND_TIMEOUT) as client:
                await client.post(
                    f"{BACKEND_URL}/farmer/advisory/feedback",
                    json={"message_id": advisory_msg_id, "score": score},
                )
        except Exception as exc:
            logger.warning("Could not persist advisory feedback: %s", exc)
    else:
        logger.debug("No advisory message_id in FSM state — feedback not persisted.")

    await cb.message.edit_reply_markup(reply_markup=main_menu_keyboard())
    await cb.answer(ack, show_alert=False)
