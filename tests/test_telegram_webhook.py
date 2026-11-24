"""
tests/test_telegram_webhook.py — Automated Unit Tests for Telegram Webhook Integration

Tests:
1. Webhook returns 404 when TELEGRAM_BOT_TOKEN is unset/empty.
2. Webhook rejects missing or incorrect X-Telegram-Bot-Api-Secret-Token with 403.
3. Webhook accepts valid secret token.
4. Webhook rejects non-JSON or malformed payload with 400.
5. Webhook dispatches valid update to aiogram dispatcher.
6. Handler exceptions are isolated without crashing the endpoint or leaking secrets.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch, MagicMock
from pydantic import SecretStr

from backend.main import app
from backend.core.config import settings


@pytest.fixture
def client():
    return TestClient(app)


def test_telegram_webhook_unconfigured_returns_404(client, monkeypatch):
    """When TELEGRAM_BOT_TOKEN is empty, endpoint fails closed with 404."""
    monkeypatch.setattr(settings, "telegram_bot_token", SecretStr(""))
    res = client.post("/webhook/telegram", json={"update_id": 12345})
    assert res.status_code == 404
    assert "not configured" in res.json()["detail"]


def test_telegram_webhook_secret_token_verification(client, monkeypatch):
    """Secret token must be verified via constant-time comparison when configured."""
    monkeypatch.setattr(settings, "telegram_bot_token", SecretStr("123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"))
    monkeypatch.setattr(settings, "telegram_webhook_secret", "correct-secret-12345")

    # Missing header -> 403
    res_missing = client.post("/webhook/telegram", json={"update_id": 1})
    assert res_missing.status_code == 403

    # Wrong header -> 403
    res_wrong = client.post(
        "/webhook/telegram",
        json={"update_id": 1},
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"},
    )
    assert res_wrong.status_code == 403

    # Correct header -> passes secret gate (proceeds to update validation)
    with patch("backend.routers.telegram_webhook.get_telegram_components") as mock_comp:
        mock_bot, mock_dp = MagicMock(), MagicMock()
        mock_dp.feed_update = AsyncMock(return_value=None)
        mock_comp.return_value = (mock_bot, mock_dp)

        res_ok = client.post(
            "/webhook/telegram",
            json={"update_id": 999999},
            headers={"X-Telegram-Bot-Api-Secret-Token": "correct-secret-12345"},
        )
        assert res_ok.status_code == 200
        assert res_ok.json()["ok"] is True


def test_telegram_webhook_malformed_update_returns_400(client, monkeypatch):
    """Malformed payloads or non-JSON input return HTTP 400."""
    monkeypatch.setattr(settings, "telegram_bot_token", SecretStr("123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"))
    monkeypatch.setattr(settings, "telegram_webhook_secret", "")

    # Non-dict / missing update_id
    res1 = client.post("/webhook/telegram", json={"foo": "bar"})
    assert res1.status_code == 400
    assert "Malformed" in res1.json()["detail"]

    res2 = client.post("/webhook/telegram", content=b"invalid-json")
    assert res2.status_code == 400


def test_telegram_webhook_dispatches_update_safely(client, monkeypatch):
    """Valid update is converted to aiogram Update and fed to dispatcher."""
    monkeypatch.setattr(settings, "telegram_bot_token", SecretStr("123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"))
    monkeypatch.setattr(settings, "telegram_webhook_secret", "")

    with patch("backend.routers.telegram_webhook.get_telegram_components") as mock_comp:
        mock_bot = MagicMock()
        mock_dp = MagicMock()
        mock_dp.feed_update = AsyncMock(return_value=None)
        mock_comp.return_value = (mock_bot, mock_dp)

        update_payload = {
            "update_id": 10001,
            "message": {
                "message_id": 1,
                "date": 1700000000,
                "chat": {"id": 12345678, "type": "private"},
                "from": {"id": 12345678, "is_bot": False, "first_name": "Farmer"},
                "text": "Tomato price in Kolar",
            },
        }

        res = client.post("/webhook/telegram", json=update_payload)
        assert res.status_code == 200
        assert res.json()["ok"] is True
        mock_dp.feed_update.assert_awaited_once()


def test_telegram_webhook_isolates_handler_exceptions(client, monkeypatch):
    """Dispatcher exceptions return HTTP 500 so Telegram will retry transient failures."""
    monkeypatch.setattr(settings, "telegram_bot_token", SecretStr("123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"))
    monkeypatch.setattr(settings, "telegram_webhook_secret", "")

    with patch("backend.routers.telegram_webhook.get_telegram_components") as mock_comp:
        mock_bot = MagicMock()
        mock_dp = MagicMock()
        mock_dp.feed_update = AsyncMock(side_effect=RuntimeError("Engine failure"))
        mock_comp.return_value = (mock_bot, mock_dp)

        update_payload = {
            "update_id": 10002,
            "message": {
                "message_id": 2,
                "date": 1700000000,
                "chat": {"id": 12345678, "type": "private"},
                "from": {"id": 12345678, "is_bot": False, "first_name": "Farmer"},
                "text": "Tomato price",
            },
        }

        res = client.post("/webhook/telegram", json=update_payload)
        assert res.status_code == 500
        assert "Internal processing error" in res.json()["detail"]


def test_telegram_webhook_service_unavailable_returns_503(client, monkeypatch):
    """When get_telegram_components fails or returns None, endpoint returns 503."""
    monkeypatch.setattr(settings, "telegram_bot_token", SecretStr("123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"))
    monkeypatch.setattr(settings, "telegram_webhook_secret", "")

    with patch("backend.routers.telegram_webhook.get_telegram_components", return_value=(None, None)):
        res = client.post("/webhook/telegram", json={"update_id": 999})
        assert res.status_code == 503
        assert "unavailable" in res.json()["detail"]


def test_telegram_webhook_repeated_update_delivery(client, monkeypatch):
    """Verifies that consecutive deliveries of the same update_id are accepted and dispatched safely."""
    monkeypatch.setattr(settings, "telegram_bot_token", SecretStr("123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"))
    monkeypatch.setattr(settings, "telegram_webhook_secret", "")

    with patch("backend.routers.telegram_webhook.get_telegram_components") as mock_comp:
        mock_bot = MagicMock()
        mock_dp = MagicMock()
        mock_dp.feed_update = AsyncMock(return_value=None)
        mock_comp.return_value = (mock_bot, mock_dp)

        payload = {
            "update_id": 55555,
            "message": {
                "message_id": 10,
                "date": 1700000000,
                "chat": {"id": 12345, "type": "private"},
                "from": {"id": 12345, "is_bot": False, "first_name": "Farmer"},
                "text": "Tomato price in Kolar",
            },
        }

        # First delivery
        res1 = client.post("/webhook/telegram", json=payload)
        assert res1.status_code == 200
        assert res1.json()["ok"] is True

        # Second delivery (retry)
        res2 = client.post("/webhook/telegram", json=payload)
        assert res2.status_code == 200
        assert res2.json()["ok"] is True

        assert mock_dp.feed_update.await_count == 2



@pytest.mark.parametrize("query_text", [
    "/start",
    "/help",
    "Tomato price in Kolar",
    "ಕೋಲಾರದಲ್ಲಿ ಟೊಮೇಟೊ ಬೆಲೆ ಎಷ್ಟು?",
    "Kolar dalli tomato bele eshtu?",
    "How to treat leaf curl in tomato?",
    "Declare 2 acres Tomato in Kolar",
])
def test_telegram_webhook_processes_various_farmer_queries(client, monkeypatch, query_text):
    """Verifies that English, Kannada, Kanglish, commands, and advisory queries flow cleanly."""
    monkeypatch.setattr(settings, "telegram_bot_token", SecretStr("123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"))
    monkeypatch.setattr(settings, "telegram_webhook_secret", "")

    with patch("backend.routers.telegram_webhook.get_telegram_components") as mock_comp:
        mock_bot = MagicMock()
        mock_dp = MagicMock()
        mock_dp.feed_update = AsyncMock(return_value=None)
        mock_comp.return_value = (mock_bot, mock_dp)

        update_payload = {
            "update_id": 20000,
            "message": {
                "message_id": 50,
                "date": 1700000000,
                "chat": {"id": 87654321, "type": "private"},
                "from": {"id": 87654321, "is_bot": False, "first_name": "TestFarmer"},
                "text": query_text,
            },
        }

        res = client.post("/webhook/telegram", json=update_payload)
        assert res.status_code == 200
        assert res.json()["ok"] is True
        mock_dp.feed_update.assert_awaited_once()
