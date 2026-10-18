"""
tests/test_intent_smoke.py — End-to-end smoke test for all 5 core intents.

Exercises every intent path through the real conversation_message() endpoint
with realistic input including a Telegram-style farmer_name with special chars.

This guards against silent NameError / AttributeError failures in intent
handlers that wouldn't be caught by unit tests mocking individual functions.

Coverage:
  PRICE_QUERY      — verifies type=forecast or anomaly_flagged (not error)
  DECLARE_CROP     — verifies type=declaration; exercises re.sub() farmer_name
                     sanitization (the live NameError bug found in this project)
  SATURATION_CHECK — verifies type=saturation
  AGRONOMY_ADVICE  — verifies type=advisory with non-empty text
  UNKNOWN          — no entity -> verifies type=help (not error, not crash)
"""
from __future__ import annotations

import contextlib
import datetime
from types import SimpleNamespace
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Shared helpers ────────────────────────────────────────────────────────────

def _make_db_mock_for_price(current_price: float = 2000.0, arrivals: float = 80.0) -> AsyncMock:
    """DB mock matching the exact query sequence for a PRICE_QUERY with pre-resolved entities.

    With body.intent + crop + district all explicit, _resolve_conversation_context makes
    0 queries, and price_service.get_price_forecast makes exactly 3:
    spot-price row, arrivals row, history-count probe.
    """
    from price_test_helpers import price_db

    return price_db(price=current_price, arrivals=arrivals, days_old=0)


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_smoke_price_query():
    """PRICE_QUERY intent returns type=forecast (not type=error)."""
    from backend.routers.conversation import conversation_message, ConversationRequest

    db  = _make_db_mock_for_price(current_price=2000.0)
    req = ConversationRequest(
        sender_id="test_smoke_001",
        text="tomato price in kolar",
        channel="telegram",
        intent="PRICE_QUERY",
        crop="Tomato",
        district="Kolar",
    )

    patches = [
        patch("backend.services.ml_service.MODEL",       new=MagicMock()),
        patch("backend.services.ml_service.build_features",
              new_callable=AsyncMock, return_value={}),
        patch("backend.services.ml_service.make_prediction",
              return_value={"pred": 2200.0, "low": 1800.0, "high": 2600.0}),
        patch("backend.services.ml_service.price_signal",
              return_value=("HOLD", "ಹಿಡಿದಿಡಿ")),
        patch("backend.services.ml_service.crop_prediction_meta",
              return_value={"crop_mape_pct": 13.9, "msp_floor": None}),
    ]

    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        result = await conversation_message(req, MagicMock(), db)

    assert result.get("type") in ("forecast", "anomaly_flagged"), \
        f"Expected forecast/anomaly_flagged, got: {result}"
    assert result.get("crop") is not None
    assert result.get("district") is not None


@pytest.mark.asyncio
async def test_smoke_declare_crop_with_telegram_farmer_name():
    """
    DECLARE_CROP with adversarial farmer_name exercises re.sub() sanitization.
    If 'import re' is missing from conversation.py, this raises NameError.
    prior_row.declared_at is a real datetime (not MagicMock) to pass >= cutoff.
    """
    from backend.routers.conversation import conversation_message, ConversationRequest

    # Use SimpleNamespace so declared_at is a real datetime — MagicMock attributes
    # don't reliably hold assigned datetime values through SQLAlchemy ORM access patterns.
    prior_row = SimpleNamespace(
        declared_at=datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc),
        area_acres=1.5,
    )

    db = AsyncMock()
    prior_res       = MagicMock(); prior_res.scalar_one_or_none.return_value = prior_row
    prior_today_res = MagicMock(); prior_today_res.scalar_one_or_none.return_value = None

    # When body.crop, body.district, and body.intent are explicitly set:
    # 1. _resolve_conversation_context makes 0 queries.
    # 2. _get_previous_intent is NOT called (intent is DECLARE_CROP, not UNKNOWN).
    # 3. _handle_declare query 1: prior dedup check
    # 4. _handle_declare query 2: prior_today check (for is_update flag)
    # 5. _handle_declare query 3: pg_insert execution
    db.execute = AsyncMock(side_effect=[
        prior_res,        # _handle_declare query 1: dedup check (prior exists in 2020 -> outside 60s window)
        prior_today_res,  # _handle_declare query 2: prior_today check (None -> not today's update)
        MagicMock(),      # _handle_declare query 3: pg_insert execution
    ])
    db.add    = MagicMock()
    db.commit = AsyncMock()

    req = ConversationRequest(
        sender_id="test_smoke_002",
        text="2 acres tomato in kolar",
        channel="telegram",
        intent="CONFIRM_DECLARE_CROP",
        crop="Tomato",
        district="Kolar",
        area=2.0,
        farmer_name="Ravi Kumar\n\t<script>",
    )

    sat_mock = {
        "saturation_pct": 35.0, "risk_level": "MEDIUM",
        "risk_kannada": "ಮಧ್ಯಮ ಅಪಾಯ",
        "farmer_count": 14, "total_area": 280.0, "emoji": "🟡",
    }

    with patch("backend.services.farmer_service.calc_saturation",
               new=AsyncMock(return_value=sat_mock)):
        result = await conversation_message(req, MagicMock(), db)

    assert result.get("type") == "declaration", \
        f"Expected type=declaration, got: {result}"
    assert result.get("crop") == "Tomato"
    assert "saturation_pct" in result


@pytest.mark.asyncio
async def test_smoke_saturation_check():
    """SATURATION_CHECK intent returns type=saturation."""
    from backend.routers.conversation import conversation_message, ConversationRequest

    db = AsyncMock()
    empty_list      = MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
    no_prior_intent = MagicMock(first=MagicMock(return_value=None))
    db.execute = AsyncMock(side_effect=[empty_list, empty_list, no_prior_intent])
    db.add    = MagicMock()
    db.commit = AsyncMock()

    req = ConversationRequest(
        sender_id="test_smoke_003",
        text="saturation onion belagavi",
        channel="telegram",
        intent="SATURATION_CHECK",
        crop="Onion",
        district="Belagavi",
    )

    sat_mock = {
        "saturation_pct": 0.0, "risk_level": "LOW",
        "risk_kannada": "ಕಡಿಮೆ ಅಪಾಯ",
        "farmer_count": 0, "total_area": 0.0, "emoji": "🟢",
    }

    with patch("backend.services.farmer_service.calc_saturation",
               new=AsyncMock(return_value=sat_mock)):
        result = await conversation_message(req, MagicMock(), db)

    assert result.get("type") == "saturation", \
        f"Expected type=saturation, got: {result}"
    assert result.get("saturation_pct") == 0.0


@pytest.mark.asyncio
async def test_smoke_agronomy_advice():
    """AGRONOMY_ADVICE intent returns type=advisory with non-empty text."""
    from backend.routers.conversation import conversation_message, ConversationRequest

    db = AsyncMock()
    empty_list      = MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
    no_prior_intent = MagicMock(first=MagicMock(return_value=None))
    db.execute = AsyncMock(side_effect=[empty_list, empty_list, no_prior_intent])
    db.add    = MagicMock()
    db.commit = AsyncMock()

    req = ConversationRequest(
        sender_id="test_smoke_004",
        text="how to treat tomato early blight?",
        channel="telegram",
    )

    with patch("backend.services.rag.get_agronomy_advice",
               new=AsyncMock(return_value="Apply copper-based fungicide every 7 days.")):
        result = await conversation_message(req, MagicMock(), db)

    assert result.get("type") == "advisory", \
        f"Expected type=advisory, got: {result}"
    assert result.get("text"), "Advisory text must not be empty"


@pytest.mark.asyncio
async def test_smoke_unknown_intent_returns_help():
    """UNKNOWN intent with no entity -> type=help or advisory."""
    from backend.routers.conversation import conversation_message, ConversationRequest

    db = AsyncMock()
    empty_list      = MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
    no_prior_intent = MagicMock(first=MagicMock(return_value=None))
    db.execute = AsyncMock(side_effect=[empty_list, empty_list, no_prior_intent])
    db.add    = MagicMock()
    db.commit = AsyncMock()

    req = ConversationRequest(
        sender_id="test_smoke_005",
        text="hello",
        channel="telegram",
    )

    result = await conversation_message(req, MagicMock(), db)

    assert result.get("type") in ("help", "advisory"), \
        f"Expected type=help or advisory for unknown intent, got: {result}"
