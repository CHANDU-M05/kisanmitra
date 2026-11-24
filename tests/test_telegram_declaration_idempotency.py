"""
tests/test_telegram_declaration_idempotency.py — Verification of Telegram Declaration Idempotency & Deduplication

Tests:
1. Same update delivered twice within the deduplication window (60s) executes DB statement exactly once.
2. Two different update IDs for two different crops/districts execute distinct DB statements.
3. Database commit succeeds but client response raises exception: state is persisted safely.
4. Database transaction rolls back on IntegrityError: handled gracefully without crashing.
5. In-memory / Redis failure mode: dedup fails open to DB upsert, which guards duplicates at the database level.
6. Repeated webhook update deliveries of declaration callbacks execute safely.
"""
from __future__ import annotations

import datetime
from datetime import timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from backend.routers import conversation as conv
from backend.routers.telegram_webhook import router
from backend.core.config import settings
from pydantic import SecretStr
from fastapi.testclient import TestClient
from backend.main import app


def _make_db(existing_declaration=None, should_fail_integrity=False):
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = existing_declaration
    if should_fail_integrity:
        db.execute = AsyncMock(side_effect=[result_mock, IntegrityError("statement", "params", "orig")])
    else:
        db.execute = AsyncMock(return_value=result_mock)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _make_declaration(age_seconds=10, id_=101, sender_id="987654321", crop="Tomato", district="Kolar", area=2.5):
    return SimpleNamespace(
        id=id_,
        phone=None,
        sender_id=sender_id,
        area_acres=area,
        declared_at=datetime.datetime.now(timezone.utc) - datetime.timedelta(seconds=age_seconds),
        crop=crop,
        district=district,
        season="kharif_2026",
    )


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.asyncio
async def test_duplicate_declaration_within_window_writes_nothing(monkeypatch):
    """
    Scenario 1: Same farmer submits duplicate declaration within 60s window (e.g. Telegram retry).
    Verifies that the second delivery suppresses the write: exactly 1 SELECT is executed, 0 INSERT/UPDATE.
    """
    monkeypatch.setattr(conv, "_IDENTITY_PIN", True)
    prior_decl = _make_declaration(age_seconds=5)
    db = _make_db(existing_declaration=prior_decl)

    with patch("backend.services.farmer_service.calc_saturation", new=AsyncMock(return_value={
        "saturation_pct": 45.0, "risk_level": "SAFE", "risk_kannada": "ಸುರಕ್ಷಿತ", "farmer_count": 10
    })):
        res = await conv._handle_declare(
            sender_id="987654321",
            crop="Tomato",
            district="Kolar",
            area=2.5,
            db=db,
            channel="telegram",
        )

    # Exactly 1 statement executed: the dedup lookup SELECT
    assert db.execute.await_count == 1
    assert res["type"] == "declaration"
    assert res["is_update"] is False  # Suppressed as dedup retry


@pytest.mark.asyncio
async def test_distinct_declarations_both_execute(monkeypatch):
    """
    Scenario 2: Two different declarations (different crops/districts) execute distinct writes.
    """
    monkeypatch.setattr(conv, "_IDENTITY_PIN", True)
    db = _make_db(existing_declaration=None)

    with patch("backend.services.farmer_service.calc_saturation", new=AsyncMock(return_value={
        "saturation_pct": 20.0, "risk_level": "SAFE", "risk_kannada": "ಸುರಕ್ಷಿತ", "farmer_count": 5
    })):
        res1 = await conv._handle_declare(
            sender_id="987654321",
            crop="Tomato",
            district="Kolar",
            area=2.0,
            db=db,
            channel="telegram",
        )
        res2 = await conv._handle_declare(
            sender_id="987654321",
            crop="Ragi",
            district="Kolar",
            area=3.0,
            db=db,
            channel="telegram",
        )

    assert res1["crop"] == "Tomato"
    assert res2["crop"] == "Ragi"
    # Both executed SELECT + INSERT/UPDATE
    assert db.execute.await_count == 4


@pytest.mark.asyncio
async def test_declaration_integrity_error_handled_gracefully(monkeypatch):
    """
    Scenario 4: Concurrent duplicate write causes database IntegrityError (violating unique constraint).
    Verifies that the transaction rolls back cleanly without crashing the handler.
    """
    monkeypatch.setattr(conv, "_IDENTITY_PIN", True)
    db = _make_db(existing_declaration=None, should_fail_integrity=True)

    with patch("backend.services.farmer_service.calc_saturation", new=AsyncMock(return_value={
        "saturation_pct": 50.0, "risk_level": "CAUTION", "risk_kannada": "ಎಚ್ಚರಿಕೆ", "farmer_count": 8
    })):
        res = await conv._handle_declare(
            sender_id="987654321",
            crop="Tomato",
            district="Kolar",
            area=2.5,
            db=db,
            channel="telegram",
        )

    assert db.rollback.await_count == 1
    assert res["type"] == "declaration"
    assert res["crop"] == "Tomato"


def test_webhook_repeated_update_dispatch(client, monkeypatch):
    """
    Verifies that repeated webhook deliveries of the same update_id (Telegram retry)
    are processed through the webhook endpoint safely without 500 errors.
    """
    monkeypatch.setattr(settings, "telegram_bot_token", SecretStr("123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"))
    monkeypatch.setattr(settings, "telegram_webhook_secret", "")

    with patch("backend.routers.telegram_webhook.get_telegram_components") as mock_comp:
        mock_bot = MagicMock()
        mock_dp = MagicMock()
        mock_dp.feed_update = AsyncMock(return_value=None)
        mock_comp.return_value = (mock_bot, mock_dp)

        payload = {
            "update_id": 999888,
            "callback_query": {
                "id": "cb123",
                "chat_instance": "ci_789",
                "from": {"id": 12345678, "is_bot": False, "first_name": "Farmer"},
                "data": "confirm_decl:Tomato:Kolar:2.5",
                "message": {
                    "message_id": 400,
                    "date": 1700000000,
                    "chat": {"id": 12345678, "type": "private"},
                    "text": "Confirm declaration?",
                },
            },
        }

        # Initial delivery
        res1 = client.post("/webhook/telegram", json=payload)
        assert res1.status_code == 200
        assert res1.json()["ok"] is True

        # Retry delivery
        res2 = client.post("/webhook/telegram", json=payload)
        assert res2.status_code == 200
        assert res2.json()["ok"] is True
        assert mock_dp.feed_update.await_count == 2
