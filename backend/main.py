"""
api/main.py - KisanMitra FastAPI Entry Point

This is the main entry point for the backend application.
It is responsible for:
1. Bootstrapping the FastAPI app and setting up CORS.
2. Managing the application lifespan (e.g., loading the ML model on startup).
3. Including all the necessary route handlers (like the Webhook for WhatsApp).
4. Providing a global exception handler to gracefully catch unhandled errors and avoid silent crashes.
"""
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.core.database import engine
from backend.routers import api_router
from backend.services import ml_service

# ── Logging ───────────────────────────────────────────────
from backend.core.logging_config import setup_kisanmitra_logging
logger = setup_kisanmitra_logging("kisanmitra.api")

# ── Lifespan ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting KisanMitra API...")
    try:
        import importlib
        init_db = importlib.import_module("scripts.00_init_db").init_db
        await init_db()
        logger.info("Database schema and idempotency indexes verified ✓")
    except Exception as e:
        logger.error(f"Database initialization warning: {e}")

    try:
        ml_service.load_model()
    except Exception as e:
        logger.error(f"Failed to load ML model: {e}")

    yield

    logger.info("Shutting down KisanMitra API...")
    await engine.dispose()


# ── App ───────────────────────────────────────────────────
app = FastAPI(
    title="KisanMitra API",
    description="Smart Crop Planning & Market Intelligence — Karnataka",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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
