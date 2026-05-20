"""
api/main.py  —  KisanMitra FastAPI application  (v2 — async PostgreSQL)

Guardrails active:
  G1 — Fuzzy crop/district matching   (api/services/message_handler.py)
  G2 — Deterministic routing          (api/services/message_handler.py)
  G3 — Sentinel-1 SAR fallback        (scripts/04_satellite_verify.py)
  G4 — 403-safe WhatsApp sender       (api/services/whatsapp.py)

Architecture note: VS-5 Completed. Routing and Services are strictly separated.
"""
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.core.database import engine
from api.routers import api_router
from api.services import ml_service

# ── Logging ───────────────────────────────────────────────
from api.core.logging_config import setup_kisanmitra_logging
logger = setup_kisanmitra_logging("kisanmitra.api")

# ── Lifespan ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting KisanMitra API...")
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
