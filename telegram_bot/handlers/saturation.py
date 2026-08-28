"""
telegram_bot/handlers/saturation.py — Saturation check flow.

State machine: menu:saturation → SaturationFlow.choosing_crop → SaturationFlow.choosing_district → result
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from telegram_bot.backend_client import send_to_engine
from telegram_bot.formatters import format_result
from telegram_bot.keyboards import crop_keyboard, district_keyboard, result_keyboard
from telegram_bot.states import SaturationFlow

router = Router()
logger = logging.getLogger("kisanmitra.telegram.saturation")


@router.callback_query(F.data == "menu:saturation")
async def start_saturation_flow(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SaturationFlow.choosing_crop)
    await cb.message.edit_text(
        "📊 *Saturation Check*\n\n"
        "See how many farmers in your district are planting the same crop.\n\n"
        "Select crop:",
        parse_mode="Markdown",
        reply_markup=crop_keyboard(namespace="sat_crop"),
    )
    await cb.answer()


@router.callback_query(SaturationFlow.choosing_crop, F.data.startswith("sat_crop:"))
async def sat_crop_chosen(cb: CallbackQuery, state: FSMContext) -> None:
    crop = cb.data.split(":", 1)[1]
    await state.update_data(crop=crop)
    await state.set_state(SaturationFlow.choosing_district)
    await cb.message.edit_text(
        f"📊 *{crop} Saturation*\n\nSelect your district:",
        parse_mode="Markdown",
        reply_markup=district_keyboard(namespace="sat_district"),
    )
    await cb.answer()


@router.callback_query(SaturationFlow.choosing_district, F.data.startswith("sat_district:"))
async def sat_district_chosen(cb: CallbackQuery, state: FSMContext) -> None:
    data     = await state.get_data()
    crop     = data["crop"]
    district = cb.data.split(":", 1)[1]

    await cb.message.edit_text(
        f"⏳ Checking saturation for *{crop}* in *{district}*…",
        parse_mode="Markdown",
    )

    result = await send_to_engine(
        sender_id=str(cb.from_user.id),
        text=f"saturation {crop} {district}",
        intent="SATURATION_CHECK",
        crop=crop,
        district=district,
    )

    await cb.message.edit_text(
        format_result(result),
        parse_mode="Markdown",
        reply_markup=result_keyboard(),
    )
    await state.clear()
    await cb.answer()
