"""
telegram_bot/bot.py — KisanMitra Telegram Bot entrypoint.

Design decisions:
  1. Redis-backed FSM storage: state survives bot restarts (farmers mid-flow are not dropped).
  2. Handlers registered in priority order: specific flows first, freetext LAST.
  3. Bot process never imports ML/RAG code — all domain logic runs in FastAPI.
  4. Polling for development; switch to webhook for production (see TELEGRAM_WEBHOOK_URL in .env).

Run:
  cd /path/to/kisanmitra
  python -m telegram_bot.bot
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis as AsyncRedis

from telegram_bot.config import REDIS_URL, TELEGRAM_BOT_TOKEN, WEBHOOK_SECRET, WEBHOOK_URL
from telegram_bot.handlers import advisory, declare, freetext, mycrops, price, saturation, start
from telegram_bot.middleware.dedup import DedupMiddleware
from telegram_bot.middleware.ratelimit import RateLimitMiddleware

logger = logging.getLogger("kisanmitra.telegram.bot")


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    )


async def main() -> None:
    _setup_logging()

    bot = Bot(
        token=TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )

    # Share one Redis connection: FSM storage + dedup middleware both use it.
    # RedisStorage manages its own connection pool internally; we open a
    # separate lightweight client for the dedup key writes so the two
    # concerns remain decoupled and won't block each other's key namespaces.
    redis_client = AsyncRedis.from_url(REDIS_URL, decode_responses=True)
    storage = RedisStorage.from_url(REDIS_URL)
    dp      = Dispatcher(storage=storage)

    # ── Idempotency middleware (registered FIRST — outer middleware) ────────────
    # Runs before routers and filters. Drops duplicate update_ids silently.
    # Fail-open: if Redis is down, passes through to the DB-level guard.
    dp.update.outer_middleware(DedupMiddleware(redis_client))
    # ── Rate limit middleware (registered SECOND) ─────────────────────────────
    # 15 requests per 60 seconds per user_id. Fail-open on Redis error.
    dp.update.outer_middleware(RateLimitMiddleware(redis_client))
    # ── Register routers (ORDER MATTERS — freetext registered last) ───────────
    dp.include_router(start.router)
    dp.include_router(price.router)
    dp.include_router(saturation.router)
    dp.include_router(declare.router)
    dp.include_router(advisory.router)
    dp.include_router(mycrops.router)
    dp.include_router(freetext.router)    # catch-all MUST be last

    # ── Populate live crop/district lists from backend ────────────────────────
    await start.populate_crop_district_lists()

    # ── Register bot commands in Telegram's command menu ──────────────────────
    from aiogram.types import BotCommand
    await bot.set_my_commands([
        BotCommand(command="start",   description="Welcome & main menu 🌾"),
        BotCommand(command="help",    description="What KisanMitra can do"),
        BotCommand(command="mycrops", description="View your sowing declarations 🌱"),
        BotCommand(command="cancel",  description="Cancel current action"),
    ])
    logger.info("Bot commands registered with Telegram.")

    # ── Start ────────────────────────────────────────────────────────────────
    if WEBHOOK_URL:
        # Production: webhook mode (async-safe — never use web.run_app() inside an async function).
        # web.run_app() is synchronous-blocking and deadlocks inside an already-running event loop.
        from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
        import aiohttp.web as web

        await bot.set_webhook(
            url=WEBHOOK_URL,
            secret_token=WEBHOOK_SECRET or None,
            drop_pending_updates=True,
        )
        app = web.Application()
        SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=WEBHOOK_SECRET).register(
            app, path="/webhook/telegram"
        )
        setup_application(app, dp, bot=bot)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host="0.0.0.0", port=8080)
        await site.start()
        logger.info("Webhook server running at 0.0.0.0:8080, endpoint /webhook/telegram")
        logger.info("Registered webhook: %s", WEBHOOK_URL)

        # Keep the event loop alive until interrupted.
        try:
            await asyncio.Event().wait()
        finally:
            await runner.cleanup()
    else:
        # Development: long-polling
        logger.info("Starting in polling mode (development).")
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
