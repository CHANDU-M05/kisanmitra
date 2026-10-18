"""
tests/test_ratelimit.py — Unit tests for RateLimitMiddleware.

Verifies:
  1. First N requests within limit pass through.
  2. Request N+1 is dropped and a reply is attempted.
  3. Redis failure is fail-open (request passes through).
  4. Updates without a user (system events) are not rate-limited.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.types import Message
from telegram_bot.middleware.ratelimit import RateLimitMiddleware


def _make_redis(incr_returns: list[int]):
    """Redis mock whose INCR returns values from the given list sequentially."""
    redis = AsyncMock()
    redis.incr = AsyncMock(side_effect=incr_returns)
    redis.expire = AsyncMock()
    return redis


def _make_event(user_id: int | None = 12345):
    """Build a minimal aiogram Update-like event and data dict using spec=Message."""
    event = MagicMock()
    if user_id is not None:
        user          = MagicMock()
        user.id       = user_id
        data          = {"event_from_user": user}
        msg           = MagicMock(spec=Message)
        msg.answer    = AsyncMock()
        event.message = msg
        event.callback_query = None
    else:
        data          = {}  # no event_from_user
        event.message = None
    return event, data


@pytest.mark.asyncio
async def test_ratelimit_passes_within_limit():
    """Requests under the limit are passed to the handler."""
    redis = _make_redis([1])   # first request in this window
    mw    = RateLimitMiddleware(redis, limit=15, window=60)

    handler = AsyncMock(return_value={"ok": True})
    event, data = _make_event()

    result = await mw(handler, event, data)

    handler.assert_called_once()
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_ratelimit_drops_over_limit():
    """Request exceeding the limit does NOT call the handler."""
    redis = _make_redis([16])  # 16th request in a window with limit=15
    mw    = RateLimitMiddleware(redis, limit=15, window=60)

    handler = AsyncMock()
    event, data = _make_event()
    # message.answer must be awaitable
    event.message.answer = AsyncMock()

    result = await mw(handler, event, data)

    handler.assert_not_called()
    event.message.answer.assert_called_once()
    assert result is None


@pytest.mark.asyncio
async def test_ratelimit_redis_failure_is_fail_open():
    """If Redis raises, the request is passed through (fail-open)."""
    redis = AsyncMock()
    redis.incr = AsyncMock(side_effect=ConnectionError("Redis down"))

    mw = RateLimitMiddleware(redis, limit=15, window=60)

    handler = AsyncMock(return_value="ok")
    event, data = _make_event()

    result = await mw(handler, event, data)

    handler.assert_called_once()
    assert result == "ok"


@pytest.mark.asyncio
async def test_ratelimit_no_user_passes_through():
    """Events with no event_from_user (system/channel posts) pass through unchecked."""
    redis = _make_redis([])  # INCR should never be called
    mw    = RateLimitMiddleware(redis, limit=15, window=60)

    handler = AsyncMock(return_value="ok")
    event, data = _make_event(user_id=None)

    result = await mw(handler, event, data)

    handler.assert_called_once()
    redis.incr.assert_not_called()
