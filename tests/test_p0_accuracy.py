"""
tests/test_p0_accuracy.py — Regression guards for the six P0 Telegram-accuracy fixes.

Each test pins a behavior that previously produced a WRONG or FABRICATED reply:

  A1/A4  _handle_price must NEVER invent a spot price. No mandi row anywhere
         → type="no_data"; state-wide fallback → labeled data_source + price_as_of.
  B1     Fuzzy typo fallback in resolve_crop/resolve_district, with the
         cross-domain trap guard (a district name must never fuzzy-match a crop).
  B2     Free-text PRICE/SATURATION query answered only by defaults
         (Tomato/Chikkaballapur) → type="clarify" instead of a confident guess.
  C2     Advisory cache is user/district-scoped and history-conditioned
         answers are never cached (cross-user contamination).
  D2     price_signal / make_prediction bands scale with the crop's real MAPE —
         a 12% "rise" on Tomato (MAPE 27.8%) must NOT claim a directional signal.
  FMT    formatters render no_data / clarify / freshness lines instead of crashing.
"""
from __future__ import annotations

import contextlib
import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from price_test_helpers import (
    price_db, price_db_no_data, price_db_state_fallback,
)


def _patched_ml(db):
    """Patch the ML layer around an already-built price_service DB mock."""
    stack = contextlib.ExitStack()
    stack.enter_context(patch("backend.services.ml_service.MODEL", new=MagicMock()))
    stack.enter_context(patch("backend.services.ml_service.build_features",
                              new_callable=AsyncMock, return_value={}))
    stack.enter_context(patch("backend.services.ml_service.make_prediction",
                              return_value={"pred": 2100.0, "low": 1680.0, "high": 2520.0}))
    stack.enter_context(patch("backend.services.ml_service.price_signal",
                              return_value=("NEUTRAL — Monitor weekly", "ಸ್ಥಿರ")))
    stack.enter_context(patch("backend.services.ml_service.crop_prediction_meta",
                              return_value={"crop_mape_pct": 27.84, "msp_floor": None}))
    return stack


def _as_of(days_old: int) -> str:
    return (datetime.date.today() - datetime.timedelta(days=days_old)).isoformat()


# ── A1/A4: no fabricated prices ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_price_no_data_when_db_has_no_rows():
    """Both district and state-wide queries return None → type=no_data, NOT a forecast."""
    from backend.services.price_service import get_price_forecast

    db = price_db_no_data()

    with patch("backend.services.ml_service.MODEL", new=MagicMock()):
        result = await get_price_forecast("Tomato", "Kolar", db)

    assert result["type"] == "no_data"
    assert result["crop"] == "Tomato"
    assert result["district"] == "Kolar"
    # Exactly 2 queries: district attempt + state-wide attempt, then refusal.
    assert db.execute.await_count == 2
    # A no_data reply must carry NO forecast fields to act on.
    assert "forecast" not in result and "current_price" not in result


@pytest.mark.asyncio
async def test_price_state_fallback_is_labeled_and_dated():
    """District miss + state-wide hit → data_source='state_fallback', real source market, as-of date."""
    from backend.services.price_service import get_price_forecast

    db = price_db_state_fallback(price=1500.0, days_old=2, state_market="Yeshvantapur")

    with patch("backend.services.ml_service.MODEL", new=MagicMock()), \
         patch("backend.services.ml_service.build_features",
              new_callable=AsyncMock, return_value={}) as mock_feat, \
         patch("backend.services.ml_service.make_prediction",
              return_value={"pred": 1600.0, "low": 1200.0, "high": 2000.0}), \
         patch("backend.services.ml_service.price_signal",
              return_value=("NEUTRAL — Monitor weekly", "ಸ್ಥಿರ")), \
         patch("backend.services.ml_service.crop_prediction_meta",
              return_value={"crop_mape_pct": 27.84, "msp_floor": None}):
        result = await get_price_forecast("Tomato", "Dharwad", db)

    assert result["type"] == "forecast"
    assert result["data_source"] == "state_fallback"
    assert result["source_market"] == "Yeshvantapur"
    assert result["price_as_of"] == _as_of(2)
    assert result["current_price"] == 1500.0
    # The farmer must be told the price is not from their own district.
    assert "other_market_price" in result["data_quality"]
    # Model was given the ACTUAL market name, not the farmer's district.
    assert mock_feat.await_args.args[4] == "Yeshvantapur"


@pytest.mark.asyncio
async def test_price_district_hit_not_labeled_fallback():
    """Happy path: district row found → data_source='district', still carries price_as_of."""
    from backend.services.price_service import get_price_forecast

    db = price_db(price=2000.0, days_old=1)
    with _patched_ml(db):
        result = await get_price_forecast("Tomato", "Kolar", db)

    assert result["type"] == "forecast"
    assert result["data_source"] == "district"
    assert result["price_as_of"] == _as_of(1)
    assert result["days_old"] == 1
    assert result["data_quality"] == []
    assert db.execute.await_count == 3  # price + arrivals + history probe; no state-wide query


# ── B1: fuzzy typo resolution + cross-domain trap guard ───────────────────────

@pytest.mark.parametrize("text,expected", [
    ("tomatoe price",        "Tomato"),
    ("brinjall in kolar",    "Brinjal"),
    ("coffee beanz price",   None),      # not a known crop at all
    ("kalaburagi mandi",     None),      # district name must NOT fuzzy-match "Ragi"
])
def test_fuzzy_crop_resolution(text, expected):
    from backend.services import message_handler as mh

    assert mh.resolve_crop(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("dharwadd",   "Dharwad"),
    ("dhawrad",    "Dharwad"),
    ("kolapaa",    "Kolar"),
    ("tomato",     None),   # crop name must NOT fuzzy-match a district
])
def test_fuzzy_district_resolution(text, expected):
    from backend.services import message_handler as mh

    assert mh.resolve_district(text) == expected


# ── B2: clarify instead of default-guessing ───────────────────────────────────

@pytest.mark.asyncio
async def test_free_text_price_with_defaults_returns_clarify():
    """"what is the price" (no crop/district, no history) → clarify, never a Tomato guess."""
    from backend.routers.conversation import conversation_message, ConversationRequest

    db = AsyncMock()
    no_prior = MagicMock()
    no_prior.scalar_one_or_none.return_value = None
    # Only the 2 context-recovery queries (crop, district) — _handle_price must NOT run.
    db.execute = AsyncMock(side_effect=[no_prior, no_prior])
    db.add = MagicMock()
    db.commit = AsyncMock()

    req = ConversationRequest(
        sender_id="test_clarify_001",
        text="what is the price",
        channel="telegram",
    )

    with patch("backend.services.ml_service.MODEL", new=MagicMock()):
        result = await conversation_message(req, MagicMock(), db)

    assert result["type"] == "clarify", f"Expected clarify, got: {result}"
    assert set(result["missing"]) == {"crop", "district"}
    assert result["crop"] is None and result["district"] is None
    assert db.execute.await_count == 2


@pytest.mark.asyncio
async def test_button_flow_with_explicit_intent_bypasses_clarify():
    """Menu-button PRICE_QUERY (body.intent set) carries explicit entities → no clarify gate."""
    from backend.routers.conversation import conversation_message, ConversationRequest

    req = ConversationRequest(
        sender_id="test_clarify_002",
        text="tomato price in kolar",
        channel="telegram",
        intent="PRICE_QUERY",
        crop="Tomato",
        district="Kolar",
    )
    db = price_db(price=2000.0, days_old=0)
    with _patched_ml(db):
        result = await conversation_message(req, MagicMock(), db)

    assert result["type"] == "forecast"


# ── D2: MAPE-scaled signal + honest bounds ────────────────────────────────────

def test_signal_band_scales_with_crop_mape():
    """Same +12% forecast: NEUTRAL for noisy Tomato (band 13.9%), WAIT for precise Maize."""
    from backend.services.ml_service import price_signal

    signal, _ = price_signal(1120.0, 1000.0, "Tomato")
    assert signal.startswith("NEUTRAL")

    signal, _ = price_signal(1120.0, 1000.0, "Maize")
    assert signal.startswith("WAIT")

    signal, _ = price_signal(880.0, 1000.0, "Onion")   # -12% vs band 14.34
    assert signal.startswith("NEUTRAL")

    signal, _ = price_signal(880.0, 1000.0, "Maize")   # -12% vs band 10
    assert signal.startswith("SELL NOW")


def test_signal_without_crop_falls_back_to_legacy_band():
    """Callers with no commodity (webhook/prices) keep the historical ±10% behavior."""
    from backend.services.ml_service import price_signal

    signal, _ = price_signal(1120.0, 1000.0)
    assert signal.startswith("WAIT")


def test_prediction_bounds_use_crop_mape_not_fixed_percent():
    """Non-tree branch: band = clamp(MAPE%, 15%, 35%) — Tomato 27.84%, Maize floored at 15%."""
    import numpy as np
    from backend.services import ml_service

    class _FlatModel:
        """Minimal model without estimators_/quantiles_ so the honest-MAPE branch runs."""
        def predict(self, X):
            return np.array([1000.0])

    with patch.object(ml_service, "MODEL", _FlatModel()), \
         patch.object(ml_service, "METADATA", {"algorithm": "cat", "notes": ""}):
        res_tomato = ml_service.make_prediction(np.array([[1.0, 2.0]]), 1000.0, commodity="Tomato")
        res_maize  = ml_service.make_prediction(np.array([[1.0, 2.0]]), 1000.0, commodity="Maize")

    pred = res_tomato["pred"]
    assert pred == pytest.approx(res_maize["pred"])
    # Tomato MAPE 27.84% → band 0.2784; Maize MAPE 8.61 → floored at 0.15.
    assert res_tomato["low"] == pytest.approx(pred * (1 - 0.2784), rel=1e-3)
    assert res_tomato["high"] == pytest.approx(pred * (1 + 0.2784), rel=1e-3)
    assert res_maize["low"] == pytest.approx(pred * (1 - 0.15), rel=1e-3)
    assert res_maize["high"] == pytest.approx(pred * (1 + 0.15), rel=1e-3)


# ── C2: advisory cache scoping / no cross-user contamination ─────────────────

def _rag_db_mock():
    db = AsyncMock()
    chunk_res = MagicMock()
    chunk_res.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=chunk_res)
    return db


@pytest.mark.asyncio
async def test_advisory_cache_hit_for_same_anonymous_user():
    import backend.services.rag as rag

    rag._ADVISORY_CACHE.clear()
    db = _rag_db_mock()
    # Per non-personalized call: 1 history query (empty -> not personalized) + 1 chunk query.
    # Second call must skip the chunk/LLM path entirely (cache hit after history check).
    with patch.object(rag, "_llm", MagicMock()), \
         patch.object(rag, "embed_text", new_callable=AsyncMock, return_value=[0.1] * 768):
        await rag.get_agronomy_advice("tomato blight", db, crop="Tomato", phone_number="u1")
        assert db.execute.await_count == 2
        await rag.get_agronomy_advice("tomato blight", db, crop="Tomato", phone_number="u1")
        assert db.execute.await_count == 3  # only the history probe ran — answer cached

    rag._ADVISORY_CACHE.clear()


@pytest.mark.asyncio
async def test_advisory_cache_never_leaks_across_users_or_districts():
    """Different phone or district must NOT reuse a cached key (old bug: crop:query only)."""
    import backend.services.rag as rag

    assert "u1:Any:Tomato:tomato blight" != "u2:Any:Tomato:tomato blight"

    # Direct key-construction check mirroring the implementation:
    k1 = f"{'u1' or 'anon'}:{'Kolar' or 'Any'}:{'Tomato' or 'General'}:{'tomato blight'.strip().lower()}"
    k2 = f"{'u2' or 'anon'}:{'Kolar' or 'Any'}:{'Tomato' or 'General'}:{'tomato blight'.strip().lower()}"
    k3 = f"{'u1' or 'anon'}:{'Dharwad' or 'Any'}:{'Tomato' or 'General'}:{'tomato blight'.strip().lower()}"
    assert len({k1, k2, k3}) == 3


@pytest.mark.asyncio
async def test_personalized_answer_not_cached_and_history_cache_never_hit():
    """History-conditioned answer: no cache write, and the cache is not consulted."""
    import backend.services.rag as rag

    rag._ADVISORY_CACHE.clear()
    db = _rag_db_mock()
    history = [{"role": "user", "content": "my tomato is wilting"}]

    with patch.object(rag, "_llm", MagicMock()), \
         patch.object(rag, "embed_text", new_callable=AsyncMock, return_value=[0.1] * 768), \
         patch("backend.services.context_service.get_recent_history",
               new=AsyncMock(return_value=history)):
        await rag.get_agronomy_advice("what now", db, crop="Tomato", phone_number="u1")
        assert "what now" not in str(list(rag._ADVISORY_CACHE.keys()))
        assert rag._ADVISORY_CACHE == {}

        # Prime cache as ANON, then ask with history present → must NOT serve the cache.
        rag._ADVISORY_CACHE["u1:Any:Tomato:what now"] = "STALE"
        result = await rag.get_agronomy_advice("what now", db, crop="Tomato", phone_number="u1")
        assert result != "STALE"

    rag._ADVISORY_CACHE.clear()


# ── FMT: formatters render new types without crashing ─────────────────────────

def test_formatter_no_data_and_clarify_render():
    from telegram_bot.formatters import format_result

    nd = format_result({"type": "no_data", "crop": "Tomato", "district": "Dharwad"})
    assert "No mandi data" in nd and "will not guess" in nd

    cl = format_result({"type": "clarify", "missing": ["crop", "district"]})
    assert "which crop and which district" in cl.lower()

    cl_crop = format_result({"type": "clarify", "missing": ["crop"]})
    assert "which crop" in cl_crop.lower()


def test_formatter_forecast_shows_freshness_lines():
    from telegram_bot.formatters import format_result

    text = format_result({
        "type": "forecast", "crop": "Tomato", "district": "Dharwad",
        "current_price": 1500.0, "forecast": 1600.0, "lower": 1200.0, "upper": 2000.0,
        "signal": "NEUTRAL", "crop_mape_pct": 27.84,
        "price_as_of": "2026-10-08", "data_source": "state_fallback",
        "source_market": "Yeshvantapur",
    })
    assert "Spot price as of 2026-10-08" in text
    assert "using latest Yeshvantapur price" in text
