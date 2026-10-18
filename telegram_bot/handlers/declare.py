"""
telegram_bot/handlers/declare.py — Sowing declaration flow.

State machine:
  menu:declare → DeclareCropFlow.choosing_crop
              → DeclareCropFlow.choosing_district
              → DeclareCropFlow.entering_area (text input)
              → result (declaration + saturation)
"""
from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from telegram_bot.backend_client import send_to_engine
from telegram_bot.formatters import format_result
from telegram_bot.keyboards import crop_keyboard, district_keyboard, main_menu_keyboard
from telegram_bot.messaging import answer_safe, edit_safe
from telegram_bot.states import DeclareCropFlow

router = Router()
logger = logging.getLogger("kisanmitra.telegram.declare")

_AREA_RE = re.compile(r"[\d.]+")


@router.callback_query(F.data == "menu:declare")
async def start_declare_flow(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(DeclareCropFlow.choosing_crop)
    await cb.message.edit_text(
        "🌱 *Declare Your Crop*\n\n"
        "Register your sowing so other farmers in your district can plan better.\n\n"
        "Select the crop you are planting:",
        parse_mode="Markdown",
        reply_markup=crop_keyboard(namespace="declare_crop"),
    )
    await cb.answer()


@router.callback_query(DeclareCropFlow.choosing_crop, F.data.startswith("declare_crop:"))
async def declare_crop_chosen(cb: CallbackQuery, state: FSMContext) -> None:
    crop = cb.data.split(":", 1)[1]
    await state.update_data(crop=crop)
    await state.set_state(DeclareCropFlow.choosing_district)
    await cb.message.edit_text(
        f"🌱 Declaring *{crop}*\n\nSelect your district:",
        parse_mode="Markdown",
        reply_markup=district_keyboard(namespace="declare_district"),
    )
    await cb.answer()


@router.callback_query(DeclareCropFlow.choosing_district, F.data.startswith("declare_district:"))
async def declare_district_chosen(cb: CallbackQuery, state: FSMContext) -> None:
    district = cb.data.split(":", 1)[1]
    await state.update_data(district=district)
    await state.set_state(DeclareCropFlow.entering_area)
    data = await state.get_data()
    await cb.message.edit_text(
        f"🌱 Declaring *{data['crop']}* in *{district}*\n\n"
        f"How many acres are you planting?\n"
        f"_Type a number, e.g.: `2.5`_",
        parse_mode="Markdown",
    )
    await cb.answer()


@router.message(DeclareCropFlow.entering_area)
async def area_entered(message: Message, state: FSMContext) -> None:
    raw = message.text or ""
    nums = _AREA_RE.findall(raw)

    if not nums:
        await message.answer(
            "⚠️ Please enter the number of acres as a number, e.g.: `2` or `1.5`",
            parse_mode="Markdown",
        )
        return

    area = float(nums[0])
    if area <= 0 or area > 5000:
        await message.answer(
            "⚠️ Area should be between 0.1 and 5000 acres. Please try again."
        )
        return

    data     = await state.get_data()
    crop     = data["crop"]
    district = data["district"]

    await message.answer(
        f"⏳ Registering your *{crop}* ({area} acres) in *{district}*…",
        parse_mode="Markdown",
    )

    farmer_name = message.from_user.full_name if message.from_user else None

    result = await send_to_engine(
        sender_id=str(message.from_user.id),
        text=f"{area} acres {crop} in {district}",
        intent="DECLARE_CROP",
        crop=crop,
        district=district,
        area=area,
        farmer_name=farmer_name,
    )

    await answer_safe(
        message,
        format_result(result),
        reply_markup=main_menu_keyboard(),
    )
    await state.clear()


@router.callback_query(F.data.startswith("confirm_decl:"))
async def confirm_declaration_callback(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    if len(parts) < 4:
        await cb.answer("Invalid request data.")
        return
    
    crop, district, area_str = parts[1], parts[2], parts[3]
    try:
        area = float(area_str)
    except ValueError:
        area = 1.0

    farmer_name = cb.from_user.full_name if cb.from_user else None

    await cb.answer("Recording declaration in database...")
    result = await send_to_engine(
        sender_id=str(cb.from_user.id),
        text=f"confirm declaration {area} acres {crop} in {district}",
        intent="CONFIRM_DECLARE_CROP",
        crop=crop,
        district=district,
        area=area,
        farmer_name=farmer_name,
    )

    await edit_safe(
        cb.message,
        format_result(result),
        reply_markup=main_menu_keyboard(),
    )


@router.callback_query(F.data == "cancel_decl")
async def cancel_declaration_callback(cb: CallbackQuery) -> None:
    await cb.answer("Declaration cancelled.")
    await cb.message.edit_text(
        "❌ *Declaration Cancelled*\n\nNo changes were made to the database.",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )
