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
import os
import sys
from pathlib import Path

# Allow importing backend.core from the project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from backend.core.config import settings
from backend.core.database import Base

# Import all models so Base.metadata is populated
from backend.core.models import (  # noqa: F401
    CropDeclaration,
    Farmer,
    KnowledgeChunk,
    MandiPrice,
    AdminUser,
    RevokedToken,
    ChatHistory,
)

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def init_db() -> None:
    engine = create_async_engine(settings.database_url, echo=False)

    print("\n── Enabling PostgreSQL extensions ──")
    # Extensions are only meaningful when the ORM was imported with the
    # matching DB_HAS_* flag (see backend/core/models.py); otherwise no column
    # uses them. Gate creation on that same explicit configuration so a
    # PostGIS-less pgvector image is a deliberate "not requested" skip rather
    # than a database error swallowed by a bare except. When an extension IS
    # required, a genuine failure (missing control file, no privilege) must
    # surface instead of silently producing a schema the app cannot use.
    requested = {
        "postgis": os.getenv("DB_HAS_POSTGIS", "").lower() in ("1", "true", "yes"),
        "vector": os.getenv("DB_HAS_PGVECTOR", "").lower() in ("1", "true", "yes"),
    }
    for ext, is_required in requested.items():
        if not is_required:
            print(f"   {ext} – not requested (set DB_HAS_{ext.upper()}); skipped")
            continue
        async with engine.begin() as conn:
            await conn.execute(sa.text(f"CREATE EXTENSION IF NOT EXISTS {ext};"))
        print(f"   {ext} ✓")

    print("\n── Creating tables ──")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("   All tables created ✓")

    print("\n── Applying idempotency index & schema updates (safe to re-run) ──")
    # Base.metadata.create_all only creates missing tables/indexes for NEW databases.
    # For EXISTING databases, we clean up any pre-existing duplicate rows first,
    # then issue CREATE UNIQUE INDEX IF NOT EXISTS explicitly.
    # PostgreSQL advisory lock 888999 ensures multi-worker concurrent app boots race safely.
    async with engine.begin() as conn:
        try:
            await conn.execute(sa.text("SELECT pg_advisory_lock(888999);"))
        except Exception:
            pass  # Non-PostgreSQL dialects (e.g. SQLite) ignore advisory locks

        try:
            # Deduplicate existing rows prior to index creation (keeps highest ID)
            await conn.execute(sa.text("""
                DELETE FROM crop_declarations a
                USING crop_declarations b
                WHERE a.id < b.id
                  AND lower(a.phone) = lower(b.phone)
                  AND lower(a.crop) = lower(b.crop)
                  AND lower(a.district) = lower(b.district)
                  AND a.season = b.season;
            """))
            await conn.execute(sa.text("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_decl_phone_crop_district_season
                ON crop_declarations (lower(phone), lower(crop), lower(district), season);
            """))
            await conn.execute(sa.text("""
                ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS channel VARCHAR(20) DEFAULT 'web';
            """))
            await conn.execute(sa.text("""
                ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS crop VARCHAR(100);
            """))
            await conn.execute(sa.text("""
                ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS district VARCHAR(100);
            """))
        finally:
            try:
                await conn.execute(sa.text("SELECT pg_advisory_unlock(888999);"))
            except Exception:
                pass
    print("   uq_decl_phone_crop_district_season & chat_history entity/channel columns ✓")
    
    print("\n── Seeding Admin User ──")
    from sqlalchemy.orm import sessionmaker
    async_session = sessionmaker(engine, class_=sa.ext.asyncio.AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        result = await session.execute(sa.select(AdminUser).where(AdminUser.username == "admin"))
        if not result.scalar_one_or_none():
            hashed_pw = pwd_context.hash("admin123")
            admin = AdminUser(username="admin", hashed_password=hashed_pw)
            session.add(admin)
            await session.commit()
            print("   Default admin user seeded (admin / admin123) ✓")
        else:
            print("   Admin user already exists ✓")

    await engine.dispose()
    print("\n✅  KisanMitra DB initialized. Ready for data ingestion.\n")


if __name__ == "__main__":
    asyncio.run(init_db())
