"""
tests/test_anomaly_gate.py — Verification of Anomaly Detection & Safety Gate wiring.

Tests the safety gate flow:
1. test_price_anomaly_flagged_on_high_deviation — verifies _handle_price returns type="anomaly_flagged" beyond the crop-aware gate.
2. test_formatter_renders_anomaly_alert — verifies format_result renders Anomaly Alert Markdown for type="anomaly_flagged".
3. MAPE-aware gate tests — the flag means "beyond what the model can explain":
   volatile crops (Tomato/Marigold ~28-31% benchmark MAPE) are no longer
   labelled SPIKE/CRASH on deviations inside their own error range, and every
   response carries the threshold the backend actually applied.
"""
from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from price_test_helpers import price_db


@pytest.mark.asyncio
async def test_price_anomaly_flagged_on_high_deviation():
    """
    When forecasted price deviates past the crop-aware gate (50% > Tomato's
    max(30%, 1.5x 27.8) = 41.7%), _handle_price must set
    type="anomaly_flagged", triggering human-in-the-loop validation.
    """
    from backend.routers.conversation import _handle_price

    # Fresh spot price = 1000 so the forecast is allowed at all (freshness gate).
    db = price_db(price=1000.0, arrivals=50.0, days_old=0)

    with patch("backend.services.ml_service.MODEL", new=MagicMock()), \
         patch("backend.services.ml_service.build_features", new_callable=AsyncMock) as mock_feat, \
         patch("backend.services.ml_service.make_prediction") as mock_pred, \
         patch("backend.services.ml_service.price_signal") as mock_sig, \
         patch("backend.services.ml_service.crop_prediction_meta") as mock_meta:

        mock_feat.return_value = {}
        # Forecast is 1500 -> 50% deviation (>30% threshold)
        mock_pred.return_value = {"pred": 1500.0, "low": 1300.0, "high": 1700.0}
        mock_sig.return_value = ("BUY", "ಖರೀದಿಸಿ")
        mock_meta.return_value = {"crop_mape_pct": 27.8, "msp_floor": None}

        result = await _handle_price("Tomato", "Kolar", db)

        assert result["type"] == "anomaly_flagged"
        assert result["is_anomaly"] is True
        assert result["anomaly_type"] == "SPIKE"
        assert result["deviation_pct"] == 50.0
        # The gate travels with the response: 27.8 * 1.5 -> 41.7.
        assert result["anomaly_threshold_pct"] == 41.7


@pytest.mark.asyncio
async def test_price_normal_forecast_on_low_deviation():
    """
    When forecasted price deviates inside the gate (e.g. 20%), _handle_price
    must set type="forecast" and is_anomaly=False.
    """
    from backend.routers.conversation import _handle_price

    # Fresh spot price = 1000 so the forecast is allowed at all (freshness gate).
    db = price_db(price=1000.0, arrivals=50.0, days_old=0)

    with patch("backend.services.ml_service.MODEL", new=MagicMock()), \
         patch("backend.services.ml_service.build_features", new_callable=AsyncMock) as mock_feat, \
         patch("backend.services.ml_service.make_prediction") as mock_pred, \
         patch("backend.services.ml_service.price_signal") as mock_sig, \
         patch("backend.services.ml_service.crop_prediction_meta") as mock_meta:

        mock_feat.return_value = {}
        # Forecast is 1200 -> 20% deviation (<=30% threshold)
        mock_pred.return_value = {"pred": 1200.0, "low": 1050.0, "high": 1350.0}
        mock_sig.return_value = ("HOLD", "ಹಿಡಿದಿಡಿ")
        mock_meta.return_value = {"crop_mape_pct": 13.9, "msp_floor": None}

        result = await _handle_price("Tomato", "Kolar", db)

        assert result["type"] == "forecast"
        assert result["is_anomaly"] is False
        assert result["anomaly_type"] == "SPIKE"  # calculated based on pred > current
        assert result["deviation_pct"] == 20.0
        # MAPE 13.9 * 1.5 = 20.85, floored at the legacy 30% gate.
        assert result["anomaly_threshold_pct"] == 30.0


@pytest.mark.asyncio
async def test_volatile_crop_noise_is_not_labelled_a_market_anomaly():
    """
    A +32% Tomato deviation exceeds the old fixed 30% gate but sits inside the
    model's own benchmark error (MAPE 27.84 -> gate 41.8%). It must now be
    returned as a plain forecast — the CI, signal and crop_mape_pct still
    travel with the response, so nothing is hidden, only re-labelled honestly.
    """
    from backend.routers.conversation import _handle_price

    db = price_db(price=1000.0, arrivals=50.0, days_old=0)

    with patch("backend.services.ml_service.MODEL", new=MagicMock()), \
         patch("backend.services.ml_service.build_features", new_callable=AsyncMock) as mock_feat, \
         patch("backend.services.ml_service.make_prediction") as mock_pred, \
         patch("backend.services.ml_service.price_signal") as mock_sig, \
         patch("backend.services.ml_service.crop_prediction_meta") as mock_meta:

        mock_feat.return_value = {}
        mock_pred.return_value = {"pred": 1320.0, "low": 1000.0, "high": 1700.0}
        mock_sig.return_value = ("WAIT — Price likely rising", "ಕಾಯಿರಿ")
        mock_meta.return_value = {"crop_mape_pct": 27.84, "msp_floor": None}

        result = await _handle_price("Tomato", "Kolar", db)

        assert result["type"] == "forecast"
        assert result["is_anomaly"] is False
        assert result["deviation_pct"] == 32.0
        assert result["anomaly_threshold_pct"] == 41.8
        # Honesty payload is untouched — re-labelling must not strip context.
        assert result["crop_mape_pct"] == 27.84
        assert result["lower"] == 1000.0 and result["upper"] == 1700.0
        assert result["signal"] == "WAIT — Price likely rising"


def test_anomaly_threshold_is_crop_mape_aware_and_floored():
    """Helper contract: gate = max(30%, 1.5x crop MAPE); unknown crops keep 30%.

    CROP_MAPE is pinned so the test covers the gate arithmetic, independent of
    whether load_model() has already reconciled the table with metadata.
    """
    from backend.services import ml_service

    with patch.object(ml_service, "CROP_MAPE", {"Maize": 8.61, "Tomato": 27.84, "Marigold": 30.65}):
        assert ml_service.anomaly_threshold_pct("Maize") == 30.0          # 8.61*1.5=12.9 -> floored
        assert ml_service.anomaly_threshold_pct("Tomato") == 27.84 * 1.5  # 41.76
        assert ml_service.anomaly_threshold_pct("Marigold") == 30.65 * 1.5
        assert ml_service.anomaly_threshold_pct("Coriander") == 30.0      # not in benchmark
        assert ml_service.anomaly_threshold_pct(None) == 30.0
    # An explicit crop_mape (as price_service passes from crop_prediction_meta)
    # overrides the table lookup.
    assert ml_service.anomaly_threshold_pct("Tomato", 10.0) == 30.0
    assert ml_service.anomaly_threshold_pct("Tomato", 40.0) == 60.0


def test_formatter_renders_anomaly_alert():
    """
    Verifies format_result correctly routes anomaly_flagged results to format_anomaly.
    """
    from telegram_bot.formatters import format_result

    anomaly_data = {
        "type": "anomaly_flagged",
        "crop": "Tomato",
        "district": "Kolar",
        "current_price": 1000.0,
        "forecast": 1500.0,
        "deviation_pct": 50.0,
        "anomaly_type": "SPIKE",
    }

    formatted = format_result(anomaly_data)

    assert "Anomaly Alert" in formatted
    assert "Human-in-the-Loop Validation Active" in formatted
    assert "50.0%" in formatted
    # No server-supplied threshold in this legacy-shaped payload: the bot must
    # disclose the historical 30% floor rather than silently invent a new one.
    assert "threshold: 30%" in formatted


def test_formatter_discloses_crop_aware_threshold():
    """
    When the backend sends the gate it applied (Tomato: 41.8%), the anomaly
    message must show that number and why it is above the 30% floor — the
    bot can no longer claim a hardcoded 30% the server never used.
    """
    from telegram_bot.formatters import format_anomaly

    formatted = format_anomaly({
        "type": "anomaly_flagged",
        "crop": "Tomato",
        "district": "Kolar",
        "current_price": 1000.0,
        "forecast": 1500.0,
        "lower": 1300.0,
        "upper": 1700.0,
        "deviation_pct": 50.0,
        "anomaly_threshold_pct": 41.8,
        "anomaly_type": "SPIKE",
        "crop_mape_pct": 27.84,
    })

    assert "threshold: 41.8%" in formatted
    assert "beyond what the model's own error explains" in formatted
    assert "benchmark MAPE: 27.8%" in formatted
    assert "threshold: 30%)" not in formatted


# ── Amendment: non-finite hardening ───────────────────────────────────────────

@pytest.mark.parametrize("bad_mape", [math.nan, math.inf, -math.inf, "27.8", float, True, -5.0, 0.0])
def test_non_finite_or_invalid_mape_degrades_to_the_floor(bad_mape):
    """A corrupt MAPE must never produce a NaN/inf gate — that would switch
    anomaly detection off (NaN comparisons are always False) and leak an
    invalid literal into the JSON. Every invalid value degrades to 30%."""
    from backend.services.ml_service import anomaly_threshold_pct

    assert anomaly_threshold_pct("Tomato", bad_mape) == 30.0


def test_missing_mape_falls_back_to_table_then_floor():
    """crop_mape=None is the documented 'use the table' signal, not corrupt
    input: known crops resolve through CROP_MAPE, and a crop missing from
    every source still lands on the 30% floor."""
    from backend.services import ml_service

    with patch.object(ml_service, "CROP_MAPE", {"Tomato": 27.84}):
        assert ml_service.anomaly_threshold_pct("Tomato", None) == 27.84 * 1.5
        assert ml_service.anomaly_threshold_pct("Coriander", None) == 30.0


@pytest.mark.asyncio
async def test_deviation_exactly_at_threshold_is_not_flagged():
    """Boundary contract: the gate is a strict `>` — 30.0 vs a 30.0 floor
    (low-MAPE crop) must NOT be labelled an anomaly."""
    from backend.routers.conversation import _handle_price

    db = price_db(price=1000.0, arrivals=50.0, days_old=0)

    with patch("backend.services.ml_service.MODEL", new=MagicMock()), \
         patch("backend.services.ml_service.build_features", new_callable=AsyncMock) as mock_feat, \
         patch("backend.services.ml_service.make_prediction") as mock_pred, \
         patch("backend.services.ml_service.price_signal", return_value=("NEUTRAL — Monitor weekly", "ಸ್ಥಿರ")), \
         patch("backend.services.ml_service.crop_prediction_meta") as mock_meta:

        mock_feat.return_value = {}
        mock_pred.return_value = {"pred": 1300.0, "low": 1100.0, "high": 1500.0}
        mock_meta.return_value = {"crop_mape_pct": 8.5, "msp_floor": None}  # floored gate: 30.0

        result = await _handle_price("Maize", "Kolar", db)

        assert result["type"] == "forecast"
        assert result["is_anomaly"] is False
        assert result["deviation_pct"] == 30.0
        assert result["anomaly_threshold_pct"] == 30.0


@pytest.mark.asyncio
async def test_deviation_just_above_threshold_is_flagged():
    """30.1% over the same 30.0 floor must flip to anomaly_flagged — the gate
    is strict `>`, not `>=`, and is sensitive at the boundary."""
    from backend.routers.conversation import _handle_price

    db = price_db(price=1000.0, arrivals=50.0, days_old=0)

    with patch("backend.services.ml_service.MODEL", new=MagicMock()), \
         patch("backend.services.ml_service.build_features", new_callable=AsyncMock) as mock_feat, \
         patch("backend.services.ml_service.make_prediction") as mock_pred, \
         patch("backend.services.ml_service.price_signal", return_value=("NEUTRAL — Monitor weekly", "ಸ್ಥಿರ")), \
         patch("backend.services.ml_service.crop_prediction_meta") as mock_meta:

        mock_feat.return_value = {}
        mock_pred.return_value = {"pred": 1301.0, "low": 1100.0, "high": 1500.0}
        mock_meta.return_value = {"crop_mape_pct": 8.5, "msp_floor": None}

        result = await _handle_price("Maize", "Kolar", db)

        assert result["type"] == "anomaly_flagged"
        assert result["is_anomaly"] is True
        assert result["deviation_pct"] == 30.1


@pytest.mark.asyncio
async def test_crash_direction_flagged_under_crop_aware_gate():
    """A 45% fall on Tomato clears the 41.8% crop-aware gate downward: type
    anomaly_flagged with anomaly_type CRASH (mirror of the SPIKE case)."""
    from backend.routers.conversation import _handle_price

    db = price_db(price=1000.0, arrivals=50.0, days_old=0)

    with patch("backend.services.ml_service.MODEL", new=MagicMock()), \
         patch("backend.services.ml_service.build_features", new_callable=AsyncMock) as mock_feat, \
         patch("backend.services.ml_service.make_prediction") as mock_pred, \
         patch("backend.services.ml_service.price_signal", return_value=("SELL NOW — Price likely falling", "ಈಗಲೇ ಮಾರಿ")), \
         patch("backend.services.ml_service.crop_prediction_meta") as mock_meta:

        mock_feat.return_value = {}
        mock_pred.return_value = {"pred": 550.0, "low": 400.0, "high": 700.0}
        mock_meta.return_value = {"crop_mape_pct": 27.84, "msp_floor": None}

        result = await _handle_price("Tomato", "Kolar", db)

        assert result["type"] == "anomaly_flagged"
        assert result["anomaly_type"] == "CRASH"
        assert result["is_anomaly"] is True
        assert result["deviation_pct"] == 45.0
        assert result["anomaly_threshold_pct"] == 41.8


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_price", [math.nan, math.inf, -math.inf])
async def test_non_finite_spot_price_refuses_instead_of_emitting_invalid_json(bad_price):
    """Postgres Float columns accept NaN/±inf. A corrupt spot price must
    produce the standard domain error (503 path), never a body carrying an
    invalid JSON literal and never a silently-disabled anomaly flag."""
    from backend.routers.conversation import _handle_price

    db = price_db(price=bad_price, arrivals=50.0, days_old=0)

    with patch("backend.services.ml_service.MODEL", new=MagicMock()), \
         patch("backend.services.ml_service.build_features", new_callable=AsyncMock) as mock_feat, \
         patch("backend.services.ml_service.make_prediction") as mock_pred, \
         patch("backend.services.ml_service.crop_prediction_meta") as mock_meta:

        mock_feat.return_value = {}
        # Echo the corrupt price back as the forecast: the 5x sanity ratio is
        # NaN-safe (comparisons are False), so the deviation gate is the guard.
        mock_pred.return_value = {"pred": bad_price, "low": bad_price, "high": bad_price}
        mock_meta.return_value = {"crop_mape_pct": 27.84, "msp_floor": None}

        result = await _handle_price("Tomato", "Kolar", db)

        assert result["type"] == "error"
        assert "on-finite" in result["detail"]
        assert "forecast" not in result


def test_formatter_degrades_on_malformed_threshold_payloads():
    """format_anomaly renders safely for string/NaN/inf/missing numerics —
    no crash, no `nan%` on screen; the floor label is used instead."""
    from telegram_bot.formatters import format_anomaly

    base = {
        "type": "anomaly_flagged", "crop": "Tomato", "district": "Kolar",
        "current_price": 1000.0, "forecast": 1500.0, "lower": 1300.0, "upper": 1700.0,
        "anomaly_type": "SPIKE",
    }
    for bad in (math.nan, math.inf, -math.inf, "41.8", None):
        out = format_anomaly({**base, "deviation_pct": 50.0,
                              "anomaly_threshold_pct": bad, "crop_mape_pct": bad})
        assert "nan%" not in out
        assert "inf%" not in out
        assert "threshold: 30%" in out   # degrades to the honest floor label
        assert "Deviation: *50.0%*" in out

    # Deviation itself malformed: labelled n/a rather than crashing.
    out = format_anomaly({**base, "deviation_pct": math.nan})
    assert "Deviation: *n/a*" in out
