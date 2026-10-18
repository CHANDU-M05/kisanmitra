"""
backend/core/database.py — SQLAlchemy Async Database Engine & Session Management

Manages PostgreSQL connection pooling, async sessions, ORM DeclarativeBase,
and FastAPI get_db dependency injection with automatic transaction rollback.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

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
