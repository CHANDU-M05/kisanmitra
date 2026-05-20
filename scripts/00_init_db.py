#!/usr/bin/env python3
"""
scripts/00_init_db.py

Bootstrap PostgreSQL for KisanMitra (run ONCE after fresh DB creation):
  1. Enable PostGIS and pgvector extensions (if available)
  2. Create all ORM tables (idempotent — safe to re-run)

Usage:
    python scripts/00_init_db.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Allow importing api.core from the project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from api.core.config import settings
from api.core.database import Base

# Import all models so Base.metadata is populated
from api.core.models import (  # noqa: F401
    CropDeclaration,
    Farmer,
    KnowledgeChunk,
    MandiPrice,
)


async def init_db() -> None:
    engine = create_async_engine(settings.database_url, echo=False)

    print("\n── Enabling PostgreSQL extensions ──")
    for ext in ["postgis", "vector"]:
        try:
            async with engine.begin() as conn:
                await conn.execute(sa.text(f"CREATE EXTENSION IF NOT EXISTS {ext};"))
            print(f"   {ext} ✓")
        except Exception:
            print(f"   {ext} ✗ (not installed — skipped)")

    print("\n── Creating tables ──")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("   All tables created ✓")

    await engine.dispose()
    print("\n✅  KisanMitra DB initialized. Ready for data ingestion.\n")


if __name__ == "__main__":
    asyncio.run(init_db())
