"""
telegram_bot/keyboards.py — Inline keyboard factories for all flows.

Rules:
  - callback_data format: "<namespace>:<value>"  (keeps handlers simple to filter)
  - All crop / district lists come from the backend /prices/crops-markets endpoint
    at startup; they fall back to hardcoded defaults if the backend is unreachable.
  - Keyboards are constructed fresh each call (no global state); aiogram caches
    nothing across user sessions on its own.
"""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ── Fallback lists (used when backend is unreachable) ────────────────────────

_DEFAULT_CROPS = [
    "Tomato", "Onion", "Potato", "Maize",
    "Ragi", "Brinjal", "Marigold",
]

_DEFAULT_DISTRICTS = [
    "Chikkaballapur", "Kolar", "Belagavi", "Mysuru",
    "Dharwad", "Davanagere", "Haveri", "Tumakuru",
    "Bengaluru Rural", "Bengaluru Urban",
]

# Updated at bot startup by handlers/start.py after querying the backend.
AVAILABLE_CROPS: list[str]     = list(_DEFAULT_CROPS)
AVAILABLE_DISTRICTS: list[str] = list(_DEFAULT_DISTRICTS)


# ── Main menu ────────────────────────────────────────────────────────────────

def main_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📈 Price Forecast",     callback_data="menu:price"),
        InlineKeyboardButton(text="📊 Saturation Check",   callback_data="menu:saturation"),
    )
    builder.row(
        InlineKeyboardButton(text="🌱 Declare My Crop",    callback_data="menu:declare"),
        InlineKeyboardButton(text="💬 Agronomy Advice",    callback_data="menu:advisory"),
    )
    builder.row(
        InlineKeyboardButton(text="ℹ️ About KisanMitra",   callback_data="menu:about"),
    )
    return builder.as_markup()


# ── Crop selection ───────────────────────────────────────────────────────────

def crop_keyboard(namespace: str = "crop") -> InlineKeyboardMarkup:
    """
    namespace: "crop" for price/saturation flows, "declare_crop" for declaration flow.
    callback_data: "<namespace>:<CropName>"
    """
    builder = InlineKeyboardBuilder()
    for crop in AVAILABLE_CROPS:
        builder.button(text=crop, callback_data=f"{namespace}:{crop}")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data="nav:menu"))
    return builder.as_markup()


# ── District selection ───────────────────────────────────────────────────────

def district_keyboard(namespace: str = "district") -> InlineKeyboardMarkup:
    """
    namespace: "district" for price/saturation, "declare_district" for declaration.
    callback_data: "<namespace>:<DistrictName>"
    """
    builder = InlineKeyboardBuilder()
    for district in AVAILABLE_DISTRICTS:
        builder.button(text=district, callback_data=f"{namespace}:{district}")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="⬅️ Back", callback_data="nav:back"))
    return builder.as_markup()


# ── Post-result actions ──────────────────────────────────────────────────────

def result_keyboard() -> InlineKeyboardMarkup:
    """Shown after a forecast or saturation result."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔄 Check Another Crop", callback_data="nav:menu"),
        InlineKeyboardButton(text="🌱 Declare This Crop",  callback_data="menu:declare"),
    )
    return builder.as_markup()


def advisory_followup_keyboard() -> InlineKeyboardMarkup:
    """Shown after an advisory answer."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="👍 Helpful",   callback_data="feedback:positive"),
        InlineKeyboardButton(text="👎 Not helpful", callback_data="feedback:negative"),
    )
    builder.row(
        InlineKeyboardButton(text="❓ Ask Another Question", callback_data="menu:advisory"),
        InlineKeyboardButton(text="🏠 Main Menu", callback_data="nav:menu"),
    )
    return builder.as_markup()


def anomaly_keyboard() -> InlineKeyboardMarkup:
    """Shown when a forecast has >30% deviation — human review required."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📋 See Saturation Instead", callback_data="menu:saturation"),
        InlineKeyboardButton(text="💬 Ask an Expert",          callback_data="menu:advisory"),
    )
    builder.row(
        InlineKeyboardButton(text="🏠 Main Menu", callback_data="nav:menu"),
    )
    return builder.as_markup()


def declaration_confirm_keyboard(crop: str, district: str, area: float) -> InlineKeyboardMarkup:
    """Confirmation keyboard before recording a sowing declaration in DB."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Record Declaration", callback_data=f"confirm_decl:{crop}:{district}:{area}"),
        InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_decl"),
    )
    return builder.as_markup()
