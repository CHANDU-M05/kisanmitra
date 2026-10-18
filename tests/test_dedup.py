"""
tests/test_dedup.py — Idempotency tests for the declaration guard.

Tests the DB-level _handle_declare guard in conversation.py.
Does not require Redis (that layer is tested separately by inspecting middleware logic).

The Redis middleware is an outer guard; the DB guard is the inner fallback.
Both are tested here:

1. test_declare_idempotent_db_guard  — second call with same sender/crop/district/season
   within 60s returns the existing record without inserting a duplicate.

2. test_declare_new_season_allowed  — same sender/crop/district but a different season
   is NOT blocked (different season = legitimate new declaration).

3. test_dedup_middleware_logic  — unit-tests the SET NX EX key logic directly,
   mocking Redis to verify first vs. duplicate behaviour.
"""
from __future__ import annotations

import datetime
from datetime import timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── DB-level guard tests ──────────────────────────────────────────────────────

class TestDeclareIdempotencyGuard:
    """
    Tests for the combined dedup + is_update logic in _handle_declare.

    The refactored code uses a single SELECT (no time-window filter in the query;
    time-window branching happens in Python) so the mock always returns the same
    result object and we control `declared_at` to trigger different branches.
    """

    def _make_db(self, existing_declaration=None):
        """Build a mock AsyncSession that returns `existing_declaration` on SELECT."""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = existing_declaration
        db.execute = AsyncMock(return_value=result_mock)
        db.add = MagicMock()
        db.commit = AsyncMock()
        return db

    def _make_declaration(self, crop="Tomato", district="Kolar", area=2.0,
                          age_seconds=10):
        """Make a mock CropDeclaration `age_seconds` old."""
        decl = MagicMock()
        decl.area_acres = area
        decl.declared_at = datetime.datetime.now(timezone.utc) - datetime.timedelta(seconds=age_seconds)
        decl.crop = crop
        decl.district = district
        return decl

    @pytest.mark.asyncio
    async def test_duplicate_within_window_not_inserted(self):
        """
        Prior row within 60s → duplicate suppression path.
        db.execute must be called once (SELECT only); upsert is never reached.
        """
        from backend.routers.conversation import _handle_declare

        existing = self._make_declaration(age_seconds=10)  # within 60s window
        db = self._make_db(existing_declaration=existing)

        with patch("backend.services.farmer_service.calc_saturation", new_callable=AsyncMock) as mock_sat:
            mock_sat.return_value = {
                "saturation_pct": 45.0,
                "risk_level": "MEDIUM",
                "risk_kannada": "ಮಧ್ಯಮ ಅಪಾಯ",
                "farmer_count": 12,
            }
            result = await _handle_declare(
                sender_id="9999999999",
                crop="Tomato",
                district="Kolar",
                area=2.0,
                db=db,
                channel="telegram",
            )

        assert result["type"] == "declaration"
        assert result["is_update"] is False       # dedup suppression, not genuine update
        assert result["area"] == 2.0
        # Only the SELECT fires; upsert is short-circuited.
        assert db.execute.call_count == 1, (
            f"Expected 1 db.execute call (SELECT only, upsert skipped), got {db.execute.call_count}"
        )

    @pytest.mark.asyncio
    async def test_first_declaration_upserts(self):
        """
        No prior row → fresh INSERT path.
        db.execute called twice: SELECT dedup + upsert.
        is_update must be False.
        """
        from backend.routers.conversation import _handle_declare

        db = self._make_db(existing_declaration=None)

        with patch("backend.services.farmer_service.calc_saturation", new_callable=AsyncMock) as mock_sat:
            mock_sat.return_value = {
                "saturation_pct": 20.0,
                "risk_level": "LOW",
                "risk_kannada": "ಕಡಿಮೆ ಅಪಾಯ",
                "farmer_count": 5,
            }
            result = await _handle_declare(
                sender_id="8888888888",
                crop="Ragi",
                district="Dharwad",
                area=1.5,
                db=db,
                channel="telegram",
            )

        assert result["type"] == "declaration"
        assert result["area"] == 1.5
        assert result["is_update"] is False       # fresh declaration
        # SELECT dedup + upsert INSERT = 2 calls
        assert db.execute.call_count == 2, (
            f"Expected 2 db.execute calls (SELECT + upsert), got {db.execute.call_count}"
        )
        db.add.assert_not_called()  # no db.add in the upsert path

    @pytest.mark.asyncio
    async def test_genuine_update_outside_window(self):
        """
        Prior row exists but is older than 60s → genuine area update.
        is_update must be True; upsert fires.
        """
        from backend.routers.conversation import _handle_declare

        old_decl = self._make_declaration(area=1.0, age_seconds=3600)  # 1 hour ago
        db = self._make_db(existing_declaration=old_decl)

        with patch("backend.services.farmer_service.calc_saturation", new_callable=AsyncMock) as mock_sat:
            mock_sat.return_value = {
                "saturation_pct": 55.0,
                "risk_level": "MEDIUM",
                "risk_kannada": "ಮಧ್ಯಮ ಅಪಾಯ",
                "farmer_count": 20,
            }
            result = await _handle_declare(
                sender_id="7777777777",
                crop="Tomato",
                district="Kolar",
                area=3.0,   # farmer updating from 1.0 to 3.0 acres
                db=db,
                channel="telegram",
            )

        assert result["type"] == "declaration"
        assert result["area"] == 3.0
        assert result["is_update"] is True        # genuine area update
        # SELECT + upsert UPDATE = 2 calls
        assert db.execute.call_count == 2


# ── Redis middleware unit tests ───────────────────────────────────────────────

class TestDedupMiddleware:
    """
    Tests for the Redis SET NX EX idempotency middleware.
    Mocks Redis so no real Redis connection is needed.
    """

    def _make_update(self, update_id: int):
        update = MagicMock()
        update.update_id = update_id
        return update

    @pytest.mark.asyncio
    async def test_first_update_passes_through(self):
        """First time an update_id is seen, the handler must be called."""
        from telegram_bot.middleware.dedup import DedupMiddleware

        redis_mock = AsyncMock()
        redis_mock.set = AsyncMock(return_value=True)  # True = SET succeeded (new key)

        handler = AsyncMock(return_value="result")
        middleware = DedupMiddleware(redis=redis_mock)

        update = self._make_update(update_id=12345)
        result = await middleware(handler, update, {})

        handler.assert_called_once()
        assert result == "result"

    @pytest.mark.asyncio
    async def test_duplicate_update_dropped(self):
        """Second delivery of same update_id — handler must NOT be called."""
        from telegram_bot.middleware.dedup import DedupMiddleware

        redis_mock = AsyncMock()
        redis_mock.set = AsyncMock(return_value=None)  # None = key already exists (duplicate)

        handler = AsyncMock(return_value="result")
        middleware = DedupMiddleware(redis=redis_mock)

        update = self._make_update(update_id=12345)
        result = await middleware(handler, update, {})

        handler.assert_not_called()
        assert result is None

    @pytest.mark.asyncio
    async def test_redis_failure_is_fail_open(self):
        """If Redis raises, the handler must still be called (fail-open policy)."""
        from telegram_bot.middleware.dedup import DedupMiddleware

        redis_mock = AsyncMock()
        redis_mock.set = AsyncMock(side_effect=ConnectionError("Redis is down"))

        handler = AsyncMock(return_value="result")
        middleware = DedupMiddleware(redis=redis_mock)

        update = self._make_update(update_id=99999)
        result = await middleware(handler, update, {})

        handler.assert_called_once()   # fail-open: handler still runs
        assert result == "result"

    @pytest.mark.asyncio
    async def test_different_update_ids_both_pass(self):
        """Two different update_ids should both pass through independently."""
        from telegram_bot.middleware.dedup import DedupMiddleware

        redis_mock = AsyncMock()
        redis_mock.set = AsyncMock(return_value=True)  # always new

        handler = AsyncMock(return_value="ok")
        middleware = DedupMiddleware(redis=redis_mock)

        for uid in [1001, 1002]:
            await middleware(handler, self._make_update(uid), {})

        assert handler.call_count == 2
