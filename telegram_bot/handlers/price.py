"""
telegram_bot/handlers/price.py — Price forecast flow.

State machine: menu:price → PriceFlow.choosing_crop → PriceFlow.choosing_district → result

Buttons build the query; both land on the same backend call.
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from telegram_bot.backend_client import send_to_engine
from telegram_bot.formatters import format_result
from telegram_bot.keyboards import (
    anomaly_keyboard,
    crop_keyboard,
    district_keyboard,
    result_keyboard,
)
from telegram_bot.states import PriceFlow

router = Router()
logger = logging.getLogger("kisanmitra.telegram.price")


@router.callback_query(F.data == "menu:price")
async def start_price_flow(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PriceFlow.choosing_crop)
    await cb.message.edit_text(
        "📈 *Price Forecast*\n\nSelect the crop you want to check:",
        parse_mode="Markdown",
        reply_markup=crop_keyboard(namespace="crop"),
    )
    await cb.answer()


@router.callback_query(PriceFlow.choosing_crop, F.data.startswith("crop:"))
async def crop_chosen(cb: CallbackQuery, state: FSMContext) -> None:
    crop = cb.data.split(":", 1)[1]
    await state.update_data(crop=crop)
    await state.set_state(PriceFlow.choosing_district)
    await cb.message.edit_text(
        f"📈 *{crop} Forecast*\n\nNow select your district:",
        parse_mode="Markdown",
        reply_markup=district_keyboard(namespace="district"),
    )
    await cb.answer()


@router.callback_query(PriceFlow.choosing_district, F.data.startswith("district:"))
async def district_chosen(cb: CallbackQuery, state: FSMContext) -> None:
    data     = await state.get_data()
    crop     = data["crop"]
    district = cb.data.split(":", 1)[1]

    await cb.message.edit_text(
        f"⏳ Fetching 60-day forecast for *{crop}* in *{district}*…",
        parse_mode="Markdown",
    )

    result = await send_to_engine(
        sender_id=str(cb.from_user.id),
        text=f"price of {crop} in {district}",
        intent="PRICE_QUERY",
        crop=crop,
        district=district,
    )

    text   = format_result(result)
    kb     = anomaly_keyboard() if result.get("type") == "anomaly_flagged" else result_keyboard()

    await cb.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    await state.clear()
    await cb.answer()
