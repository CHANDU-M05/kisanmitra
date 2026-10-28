"""
tests/test_anomaly_gate.py — Verification of Anomaly Detection & Safety Gate wiring.

Tests the safety gate flow:
1. test_price_anomaly_flagged_on_high_deviation — verifies _handle_price returns type="anomaly_flagged" on >30% shift.
2. test_formatter_renders_anomaly_alert — verifies format_result renders Anomaly Alert Markdown for type="anomaly_flagged".
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from price_test_helpers import price_db


@pytest.mark.asyncio
async def test_price_anomaly_flagged_on_high_deviation():
    """
    When forecasted price deviates >30% from current spot price, _handle_price
    must set type="anomaly_flagged", triggering human-in-the-loop validation.
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


@pytest.mark.asyncio
async def test_price_normal_forecast_on_low_deviation():
    """
    When forecasted price deviates <=30% from current spot price (e.g. 20%),
    _handle_price must set type="forecast" and is_anomaly=False.
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
