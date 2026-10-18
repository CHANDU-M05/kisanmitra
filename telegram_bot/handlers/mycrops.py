"""
telegram_bot/handlers/mycrops.py — /mycrops command.

Shows the farmer their own current-season sowing declarations.
Calls GET /api/v1/farmers/{phone}/declarations on the backend.
"""
from __future__ import annotations

import logging

import httpx
from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from telegram_bot.config import BACKEND_URL, BACKEND_TIMEOUT, INTERNAL_SECRET
from telegram_bot.keyboards import main_menu_keyboard
from telegram_bot.messaging import answer_safe

router = Router()
logger = logging.getLogger("kisanmitra.telegram.mycrops")


@router.message(Command("mycrops"))
async def mycrops_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    sender_id = str(message.from_user.id)

    try:
        async with httpx.AsyncClient(timeout=BACKEND_TIMEOUT) as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/v1/farmers/{sender_id}/declarations",
                params={"caller_id": sender_id},
                headers={"X-Internal-Secret": INTERNAL_SECRET},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        await message.answer(
            "⏳ Service is slow right now. Please try again in a moment. 🙏",
            reply_markup=main_menu_keyboard(),
        )
        return
    except Exception as exc:
        logger.warning("Could not fetch declarations for user=%s: %s", sender_id, exc)
        await message.answer(
            "⚠️ Could not retrieve your declarations. Please try again later.",
            reply_markup=main_menu_keyboard(),
        )
        return

    declarations = data.get("declarations", [])
    if not declarations:
        await message.answer(
            "🌱 *Your Sowing Declarations*\n\n"
            "You haven't declared any crops yet this season.\n\n"
            "Tap *🌱 Declare My Crop* in the menu to register your sowing.",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(),
        )
        return

    lines = ["🌱 *Your Sowing Declarations*\n"]
    for i, d in enumerate(declarations, 1):
        declared_date = d.get("declared_at", "")[:10] if d.get("declared_at") else "—"
        lines.append(
            f"*{i}. {d['crop']}* — {d['area_acres']} acres\n"
            f"   📍 {d['district']}  |  Season: {d['season']}\n"
            f"   📅 Declared: {declared_date}\n"
        )

    lines.append("\n_KisanMitra 🌾 — ಶ್ರೇಷ್ಠ ಬೆಳೆ ನಿರ್ಧಾರಗಳಿಗೆ_")

    await answer_safe(
        message,
        "\n".join(lines),
        reply_markup=main_menu_keyboard(),
    )
