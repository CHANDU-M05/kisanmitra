"""
telegram_bot/middleware/ratelimit.py — Per-user sliding-window rate limiter.

Uses Redis INCR + EXPIRE for an approximate sliding window.
Limit: 15 messages per 60 seconds per Telegram user_id.

Same fail-open contract as DedupMiddleware:
  - Redis unavailable → pass through (don't punish farmers for infra issues).
  - Breach → reply once with a gentle message and drop the update.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, Update
from redis.asyncio import Redis

logger = logging.getLogger("kisanmitra.telegram.ratelimit")

_LIMIT  = 15   # max requests
_WINDOW = 60   # per this many seconds


class RateLimitMiddleware(BaseMiddleware):
    """
    Outer middleware — runs before routing, after DedupMiddleware.
    Drops updates from users who exceed _LIMIT requests in _WINDOW seconds.
    """

    def __init__(self, redis: Redis, limit: int = _LIMIT, window: int = _WINDOW) -> None:
        self.redis  = redis
        self.limit  = limit
        self.window = window
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        # Resolve the user from whichever update type arrived.
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        try:
            key   = f"tg:rate:{user.id}"
            count = await self.redis.incr(key)
            if count == 1:
                # First request in this window — set the expiry.
                await self.redis.expire(key, self.window)
            if count > self.limit:
                logger.warning(
                    "Rate limit exceeded for user_id=%s (count=%d/%d in %ds window).",
                    user.id, count, self.limit, self.window,
                )
                # Reply on Message events; callback_query events get an answer() toast.
                actual_msg = None
                if hasattr(event, "message") and event.message:
                    actual_msg = event.message
                elif hasattr(event, "callback_query") and event.callback_query:
                    try:
                        await event.callback_query.answer(
                            "\u23f3 Too many requests \u2014 please wait a moment before trying again.",
                            show_alert=False,
                        )
                    except Exception:
                        pass
                if actual_msg and isinstance(actual_msg, Message):
                    try:
                        await actual_msg.answer(
                            "\u23f3 *Please slow down* \u2014 KisanMitra can only answer so fast!\n"
                            "Try again in a moment. \U0001f64f",
                            parse_mode="Markdown",
                        )
                    except Exception:
                        pass
                return  # Drop \u2014 do not call handler.
        except Exception as exc:
            # Redis down — fail-open.
            logger.warning(
                "Redis unavailable for rate limit check (user_id=%s): %s — passing through.",
                getattr(user, "id", "?"), exc,
            )

        return await handler(event, data)
