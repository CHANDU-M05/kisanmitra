"""
telegram_bot/middleware/dedup.py — Idempotent update processing via Redis.

WHY THIS EXISTS
===============
Telegram retries webhook delivery if a handler doesn't respond 200 within
the timeout window, or on any transient network failure. `drop_pending_updates`
only drains the queue at startup — it does nothing during normal operation.

The risk case: `_handle_declare()` writes to PostgreSQL. If the DB write
succeeds but the Telegram response is slow (or the network blips), Telegram
retries the same update_id. With no dedup, one button tap creates two
CropDeclaration rows — wrong saturation %, wrong farmer count.

Read-only handlers (forecast, saturation) are naturally idempotent.
Declaration is the only handler with a write side effect, but we dedup at
the update level (before routing) for correctness across all handlers and
to keep handler logic clean.

HOW IT WORKS
============
On every incoming update, before any handler runs:

1. Compute the Redis key:  `tg:dedup:update:{update_id}`
2. SET key "1" NX EX 90000  (NX = only if not exists, EX = TTL in seconds)
3. If SET returns None  → key already existed → duplicate → drop silently.
4. If SET returns True  → first time seeing this update → proceed normally.

TTL: 25 hours. Telegram's documented retry window is ~24 hours for failed
webhook deliveries. Any retry arriving after 25 hours is unlikely in practice
and would be a genuinely new request in that scenario.

Redis failure mode: if Redis is unavailable, the middleware logs a warning
and PASSES the update through (fail-open). The DB-level guard in
`_handle_declare` provides the second line of defence.

AIOGRAM 3.x MIDDLEWARE TYPES
=============================
Two types exist:
  - OuterMiddleware: runs before filters/handlers. Used here — we want to
    stop processing before any handler is called.
  - MiddlewareType: runs around the handler (wraps it).

We use BaseMiddleware as an outer middleware registered on the Dispatcher
via `dp.update.outer_middleware(DedupMiddleware(redis_client))`.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Update
from redis.asyncio import Redis

logger = logging.getLogger("kisanmitra.telegram.dedup")

# 25 hours: Telegram retries for up to 24h; 1-hour buffer.
_DEDUP_TTL_SECONDS = 90_000


class DedupMiddleware(BaseMiddleware):
    """
    Redis-backed idempotency middleware.

    Checks `update_id` before any handler runs. Drops silently on duplicate.
    Fail-open on Redis error: the handler still runs, and the DB-level guard
    in `_handle_declare` acts as a second line of defence.
    """

    def __init__(self, redis: Redis) -> None:
        self.redis = redis
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        update_id = event.update_id
        key       = f"tg:dedup:update:{update_id}"

        try:
            # SET key "1" NX EX ttl — atomic: returns True on first write, None on duplicate.
            is_new = await self.redis.set(key, "1", nx=True, ex=_DEDUP_TTL_SECONDS)
        except Exception as exc:
            # Redis is down — log and pass through (fail-open).
            # The DB-level guard in _handle_declare is the backup.
            logger.warning(
                "Redis unavailable for dedup check (update_id=%s): %s — passing through.",
                update_id, exc,
            )
            return await handler(event, data)

        if is_new is None:
            # Key already existed — this is a duplicate delivery.
            logger.info(
                "Duplicate update_id=%s detected — dropping silently (already processed).",
                update_id,
            )
            return  # Drop: do not call the handler.

        # First delivery — proceed normally.
        return await handler(event, data)
