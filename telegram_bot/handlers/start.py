"""
telegram_bot/handlers/start.py — /start command and main menu.

Also populates AVAILABLE_CROPS and AVAILABLE_DISTRICTS from the backend
at startup, so keyboards always reflect live DB contents.
"""
from __future__ import annotations

import logging

import httpx
from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import BotCommand, CallbackQuery, Message

from telegram_bot import keyboards
from telegram_bot.config import BACKEND_URL, BACKEND_TIMEOUT
from telegram_bot.formatters import format_about, format_help
from telegram_bot.keyboards import (
    crop_keyboard,
    main_menu_keyboard,
)
from telegram_bot.states import DeclareCropFlow, PriceFlow, SaturationFlow

router = Router()
logger = logging.getLogger("kisanmitra.telegram.start")


async def populate_crop_district_lists() -> None:
    """
    Called once at bot startup. Queries the backend to get live crops and
    districts from the PostgreSQL database.

    Two separate endpoints are used:
      /prices/crops-markets  → MandiPrice.commodity distinct values (crops)
      /prices/districts      → MandiPrice.district distinct values (admin districts)

    The district list comes from the district column (routing key used by NLP +
    farmer_service), NOT the market/mandi name column — those are different fields.
    Falls back silently to defaults if the backend is unreachable.
    """
    try:
        async with httpx.AsyncClient(timeout=BACKEND_TIMEOUT) as client:
            # Crops — from commodity column
            crops_resp = await client.get(f"{BACKEND_URL}/prices/crops-markets")
            crops_resp.raise_for_status()
            crops = crops_resp.json().get("crops", [])

            # Districts — from district column (not market/mandi names)
            dist_resp = await client.get(f"{BACKEND_URL}/prices/districts")
            dist_resp.raise_for_status()
            districts = dist_resp.json().get("districts", [])

            if crops:
                keyboards.AVAILABLE_CROPS[:] = crops
            if districts:
                keyboards.AVAILABLE_DISTRICTS[:] = districts

            logger.info(
                "Populated %d crops and %d districts from backend.",
                len(keyboards.AVAILABLE_CROPS), len(keyboards.AVAILABLE_DISTRICTS),
            )
    except Exception as exc:
        logger.warning(
            "Could not populate crops/districts from backend: %s — "
            "FALLING BACK TO HARDCODED DEFAULTS (%d crops, %d districts). "
            "Farmers will see stale keyboard lists until bot restarts.",
            exc,
            len(keyboards.AVAILABLE_CROPS),
            len(keyboards.AVAILABLE_DISTRICTS),
        )


# ── /start ───────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "🌾 *ನಮಸ್ಕಾರ! Welcome to KisanMitra* 🌾\n\n"
        "Your AI-powered crop planning assistant for Karnataka farmers.\n\n"
        "What would you like to do today?",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )


# ── Navigation callbacks ──────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "nav:menu")
async def nav_to_menu(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.message.edit_text(
        "🌾 *KisanMitra — Main Menu*\n\nWhat would you like to do?",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )
    await cb.answer()


@router.callback_query(lambda c: c.data == "menu:about")
async def show_about(cb: CallbackQuery) -> None:
    from telegram_bot.keyboards import main_menu_keyboard
    await cb.message.edit_text(
        format_about(),
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )
    await cb.answer()


# ── nav:back — returns user to the previous step in their current flow ────────

@router.callback_query(lambda c: c.data == "nav:back")
async def nav_back(cb: CallbackQuery, state: FSMContext) -> None:
    """
    Pressing ⬅️ Back from a district-selection screen returns the user to
    the crop-selection screen of the same flow, preserving FSM state.
    Any other back press clears state and returns to main menu.
    """
    current = await state.get_state()

    # Map "step 2" state → (new step-1 state, prompt text, keyboard namespace)
    back_map = {
        PriceFlow.choosing_district:       (PriceFlow.choosing_crop,      "📈 *Price Forecast*\n\nSelect the crop:",      "crop"),
        SaturationFlow.choosing_district:  (SaturationFlow.choosing_crop, "📊 *Saturation Check*\n\nSelect crop:",         "sat_crop"),
        DeclareCropFlow.choosing_district: (DeclareCropFlow.choosing_crop,"🌱 *Declare Your Crop*\n\nSelect the crop:",    "declare_crop"),
    }

    if current in back_map:
        new_state, prompt, namespace = back_map[current]
        await state.set_state(new_state)
        await cb.message.edit_text(
            prompt,
            parse_mode="Markdown",
            reply_markup=crop_keyboard(namespace=namespace),
        )
    else:
        await state.clear()
        await cb.message.edit_text(
            "🌾 *KisanMitra — Main Menu*\n\nWhat would you like to do?",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(),
        )
    await cb.answer()


# ── /help command ─────────────────────────────────────────────────────────────

@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(
        format_help(),
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )


# ── /cancel command ───────────────────────────────────────────────────────────

@router.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer(
            "✅ Nothing to cancel — you're at the main menu.",
            reply_markup=main_menu_keyboard(),
        )
        return
    await state.clear()
    await message.answer(
        "✅ Cancelled. Back to main menu.",
        reply_markup=main_menu_keyboard(),
    )
