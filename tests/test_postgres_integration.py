"""
tests/test_postgres_integration.py — Live PostgreSQL Integration Test

Verifies real PostgreSQL execution (NO mocks):
1. Runs init_db() against live PostgreSQL (verifies CREATE UNIQUE INDEX IF NOT EXISTS syntax).
2. Executes two upsert statements with identical lower/upper-case values ("tomato" vs "Tomato").
3. Asserts PostgreSQL executes ON CONFLICT (lower(phone), lower(crop), lower(district), season) without 42P10 error.
4. Asserts exactly 1 row remains in crop_declarations and area_acres is updated.
"""
from __future__ import annotations

import asyncio
import pytest
from sqlalchemy import select, func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from backend.core.config import settings
from backend.core.models import CropDeclaration
import importlib

init_db_module = importlib.import_module("scripts.00_init_db")
init_db = init_db_module.init_db


@pytest.mark.asyncio
async def test_live_postgres_upsert_and_unique_index():
    """
    REAL PostgreSQL Integration Test:
    Validates that Postgres 18.3 executes the functional unique index and ON CONFLICT
    upsert DML without 42P10 or syntax error.
    """
    # 1. Run DDL initialization on live PostgreSQL
    await init_db()

    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    test_phone = "9998887776"
    test_crop = "Tomato"
    test_district = "Kolar"
    test_season = "Kharif_Integration_Test"

    async with async_session() as session:
        # Cleanup any prior test run row
        await session.execute(
            text("DELETE FROM crop_declarations WHERE season = :s"),
            {"s": test_season}
        )
        await session.commit()

        # ── Upsert 1: First declaration (2.0 acres, uppercase "Tomato") ──
        stmt1 = (
            pg_insert(CropDeclaration)
            .values(
                farmer_name="Integration Farmer",
                phone=test_phone,
                village="Test Village",
                district=test_district,
                crop=test_crop,
                area_acres=2.0,
                season=test_season,
                trust_score=0.85,
                satellite_status="pending",
            )
            .on_conflict_do_update(
                index_elements=[
                    func.lower(CropDeclaration.phone),
                    func.lower(CropDeclaration.crop),
                    func.lower(CropDeclaration.district),
                    CropDeclaration.season,
                ],
                set_={
                    "area_acres": 2.0,
                    "farmer_name": "Integration Farmer",
                },
            )
        )
        await session.execute(stmt1)
        await session.commit()

        # Verify row was inserted
        res1 = await session.execute(
            select(CropDeclaration).where(
                CropDeclaration.phone == test_phone,
                CropDeclaration.season == test_season,
            )
        )
        rows1 = res1.scalars().all()
        assert len(rows1) == 1
        assert rows1[0].area_acres == 2.0

        # ── Upsert 2: Re-declaration with different case ("tomato", 5.0 acres) ──
        stmt2 = (
            pg_insert(CropDeclaration)
            .values(
                farmer_name="Integration Farmer Updated",
                phone=test_phone,
                village="Test Village",
                district="kolar",          # lower case
                crop="tomato",            # lower case
                area_acres=5.0,           # updated area
                season=test_season,
                trust_score=0.85,
                satellite_status="pending",
            )
            .on_conflict_do_update(
                index_elements=[
                    func.lower(CropDeclaration.phone),
                    func.lower(CropDeclaration.crop),
                    func.lower(CropDeclaration.district),
                    CropDeclaration.season,
                ],
                set_={
                    "area_acres": 5.0,
                    "farmer_name": "Integration Farmer Updated",
                },
            )
        )
        # THIS IS THE CRITICAL EXECUTION PASS: Postgres 18.3 must handle ON CONFLICT without 42P10
        await session.execute(stmt2)
        await session.commit()

        # Verify row count is STILL 1 and area_acres is updated to 5.0 using a fresh session
    async with async_session() as fresh_session:
        res2 = await fresh_session.execute(
            select(CropDeclaration).where(
                func.lower(CropDeclaration.phone) == test_phone.lower(),
                CropDeclaration.season == test_season,
            )
        )
        rows2 = res2.scalars().all()
        assert len(rows2) == 1, f"Expected exactly 1 row after conflict, got {len(rows2)}"
        assert rows2[0].area_acres == 5.0
        assert rows2[0].farmer_name == "Integration Farmer Updated"

        # Cleanup test data
        await fresh_session.execute(
            text("DELETE FROM crop_declarations WHERE season = :s"),
            {"s": test_season}
        )
        await fresh_session.commit()

    await engine.dispose()
