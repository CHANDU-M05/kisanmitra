"""
backend/core/database.py — SQLAlchemy Async Database Engine & Session Management

Manages PostgreSQL connection pooling, async sessions, ORM DeclarativeBase,
and FastAPI get_db dependency injection with automatic transaction rollback.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from backend.core.config import settings

# ── Engine ────────────────────────────────────────────────
engine = create_async_engine(
    settings.database_url,
    # Tunable per deployment: (pool_size + max_overflow) x workers x replicas
    # must stay below postgres max_connections. Defaults preserve the previous
    # hardcoded 10 + 20.
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,
    # Recycle pooled connections before a serverless proxy (Neon) drops idle
    # ones, so a wake-from-idle request re-establishes instead of erroring.
    pool_recycle=settings.db_pool_recycle,
    # libpq sslmode (require/disable/...) only when configured; empty dict
    # leaves local development behaviour identical to before.
    connect_args=settings.db_connect_args,
    # Opt-in, not tied to APP_ENV: echo prints every bound parameter, so a
    # development run would otherwise log farmer PII and any credential that
    # appears in a stored error message.
    echo=settings.db_sql_echo,
    future=True,
)

# ── Session factory ───────────────────────────────────────
AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


# ── ORM base ─────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


# ── FastAPI dependency ────────────────────────────────────
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession with automatic rollback on error."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def ensure_database_reachable() -> bool:
    """
    Open a connection, retrying on a bounded backoff.

    A Neon compute that has scaled to zero resumes on the first connection, and
    that resume can fail or stall for a few seconds. Retrying here turns a cold
    first request into a slightly slower but successful one instead of a
    spurious "database down". Returns True if the database answered, False once
    the attempts are exhausted; it never raises so callers (startup, /health)
    can degrade gracefully rather than crash.
    """
    import asyncio

    attempts = max(1, settings.db_connect_retries)
    for attempt in range(1, attempts + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(sa_text("SELECT 1"))
            return True
        except Exception:  # noqa: BLE001
            if attempt >= attempts:
                return False
            await asyncio.sleep(settings.db_connect_backoff_seconds * attempt)
    return False
