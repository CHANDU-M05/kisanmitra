"""
telegram_bot/states.py — FSM state groups for all conversation flows.

Two-layer design:
  FSM state      → which button screen the farmer is on RIGHT NOW
  ConversationContext (backend DB) → what they were talking about (for free-text follow-ups)

FSM only tracks navigation; domain context lives in Postgres via the backend.
"""
from aiogram.fsm.state import State, StatesGroup


class PriceFlow(StatesGroup):
    """Price check: crop → district → result."""
    choosing_crop     = State()
    choosing_district = State()


class SaturationFlow(StatesGroup):
    """Saturation check: crop → district → result."""
    choosing_crop     = State()
    choosing_district = State()


class DeclareCropFlow(StatesGroup):
    """Sowing declaration: crop → district → area → confirmation."""
    choosing_crop     = State()
    choosing_district = State()
    entering_area     = State()


class AdvisoryFlow(StatesGroup):
    """Agronomy Q&A: free text prompt."""
    awaiting_question = State()
