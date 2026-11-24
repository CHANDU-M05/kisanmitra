"""
api/main.py - KisanMitra FastAPI Entry Point

This is the main entry point for the backend application.
It is responsible for:
1. Bootstrapping the FastAPI app and setting up CORS.
2. Managing the application lifespan (e.g., loading the ML model on startup).
3. Including all the necessary route handlers (like the Webhook for WhatsApp).
4. Providing a global exception handler to gracefully catch unhandled errors and avoid silent crashes.
"""
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.core.database import AsyncSessionLocal, engine, ensure_database_reachable
from backend.routers import api_router
from backend.services import ml_service, scheduler
from backend.services.freshness import FRESHNESS, FreshnessSnapshot, FreshnessState

# ── Logging ───────────────────────────────────────────────
from backend.core.logging_config import setup_kisanmitra_logging
logger = setup_kisanmitra_logging("kisanmitra.api")

# ── Lifespan ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting KisanMitra API...")

    # Serve first, warm up in the background. On Render free (0.1 CPU) a
    # synchronous 57 MB unpickle before the port answers can overrun the
    # health-check window and fail the deploy, so schema init and model load
    # run as background tasks. /health returns 200 with model_loaded:false and
    # /predict answers 503 until they finish — a cold start is degraded, not
    # down.
    async def _bootstrap_database() -> None:
        # An observation is ordered by when it BEGAN, not when it finished, so
        # the stamp is taken before the awaited reachability check -- which
        # spans the whole retry/backoff window (database.ensure_database_reachable).
        # Stamping the later write moment instead would let this marker unfairly
        # outrank a concurrent observation that started mid-retry and succeeded:
        # bootstrap starts at T0, a concurrent check starts at T1 > T0 and lands
        # FRESH, bootstrap's retries finally fail at T2 > T1, and a T2 stamp would
        # overwrite that newer-but-effectively-older observation. Reused only by
        # the failed branch below; the healthy branch re-stamps via refresh().
        t_start = time.monotonic()
        if not await ensure_database_reachable():
            logger.warning("Database not reachable at startup; will retry on demand.")
            # Record WHY, and record it with the real ordering stamp captured
            # above -- the start of this failed reachability observation, never
            # the write moment. Stamping it at all keeps it from being a
            # loophole: an untimestamped marker would let a stalled older
            # success (one that started before the database actually dropped)
            # land later, erase the newer failure's ordering, and restore a
            # false FRESH + database_connected=true. The never-computed initial
            # cache snapshot deliberately stays untimestamped because nothing
            # can predate module import; this marker can and does overlap
            # concurrent freshness checks, so it must order against them.
            FRESHNESS.set(FreshnessSnapshot(
                state=FreshnessState.UNAVAILABLE,
                detail="startup could not reach the database; no freshness check ran",
                db_reachable=False,
                checked_at=t_start,
                checked_at_wall=datetime.now(timezone.utc),
            ))
            return
        try:
            import importlib
            init_db = importlib.import_module("scripts.00_init_db").init_db
            await init_db()
            logger.info("Database schema and idempotency indexes verified ✓")
        except Exception as e:
            logger.error(f"Database initialization warning: {e}")
        # Warm the shared freshness snapshot once at startup (read-only, two
        # aggregates) so /health has a real verdict to serve before the first
        # scheduler tick. Failure here stores an UNAVAILABLE snapshot — the
        # cache contract lives in backend/services/freshness.py.
        try:
            snap = await FRESHNESS.refresh(AsyncSessionLocal)
            logger.info("Startup freshness snapshot: %s", snap.state.value)
        except Exception as e:  # noqa: BLE001 — warm-up must not block serving
            logger.error("Freshness warm-up failed (health will report unavailable): %s", e)

    async def _bootstrap_model() -> None:
        loop = asyncio.get_running_loop()
        try:
            # joblib unpickling is blocking CPU work; run it off the event loop
            # so the server keeps accepting health probes while it loads.
            await loop.run_in_executor(None, ml_service.load_model)
        except Exception as e:
            logger.error(f"Failed to load ML model: {e}")

    warmup_tasks = [
        asyncio.create_task(_bootstrap_database(), name="startup-db"),
        asyncio.create_task(_bootstrap_model(), name="startup-model"),
    ]

    # Scheduled AGMARKNET ingest. The freshness gate in price_service is only
    # meaningful if something keeps the feed current, so it starts with the app
    # and is cancelled (not abandoned) on shutdown.
    refresh_task = scheduler.start_refresh_task()
    # Read-only freshness monitor: keeps /health's cached snapshot honest
    # whether or not this process owns ingestion (REFRESH_ENABLED=false).
    monitor_task = scheduler.start_freshness_monitor()

    yield

    logger.info("Shutting down KisanMitra API...")
    for task in warmup_tasks:
        if not task.done():
            task.cancel()
    await scheduler.stop_freshness_monitor(monitor_task)
    await scheduler.stop_refresh_task(refresh_task)
    try:
        from backend.routers.telegram_webhook import close_telegram_components
        await close_telegram_components()
    except Exception as e:
        logger.warning(f"Error shutting down Telegram components: {e}")
    await engine.dispose()


# ── App ───────────────────────────────────────────────────
app = FastAPI(
    title="KisanMitra API",
    description="Smart Crop Planning & Market Intelligence — Karnataka",
    version="2.0.0",
    lifespan=lifespan,
)

from backend.core.config import resolve_cors_origins, settings
from backend.core.request_guard import install_request_guard

# Origins come from a single resolver shared with validate_production_settings,
# so the middleware can never trust an origin the startup check would reject.
# There is deliberately no wildcard fallback: resolve_cors_origins drops '*'
# (credentials are never paired with a wildcard) and, when nothing valid is
# configured, only development substitutes the loopback allowlist — any other
# environment resolves to an empty list, denying every cross-origin request
# while leaving same-origin /api traffic untouched.
allow_origins = resolve_cors_origins(settings.app_env, settings.cors_origins)
if not allow_origins and settings.app_env.lower() != "development":
    logger.warning("CORS_ORIGINS is unset for app_env=%s — all cross-origin "
                   "requests are denied (fail closed).", settings.app_env)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Body-size cap + abuse-control throttle, installed as the OUTERMOST user
# middleware (registered after CORS, which Starlette makes the outermost).
# A guarded request is size- and rate-checked before anything downstream reads
# or parses it — see request_guard.py for the admission order. The limiter has
# no verified client identity in this deployment (no proxy overwriting
# X-Forwarded-For has been verified), so unidentified callers share ONE
# per-process fallback bucket: a best-effort abuse brake that can throttle
# legitimate users together, NOT per-user fairness. A verified proxy strategy
# replaces the fallback later without touching handlers.
install_request_guard(app, trust_proxy_headers=settings.trust_proxy_headers)

app.include_router(api_router)

# ── Global Exception Handler (Phase 2 Hardening) ──────────
from fastapi.responses import JSONResponse
from fastapi import Request

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled Exception on {request.url}: {repr(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred. Our engineers have been notified."},
    )
