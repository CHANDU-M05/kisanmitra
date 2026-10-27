"""
tests/test_declaration_identity.py — phone / sender_id split (Phase 1+2)

Proves the backward-compatible identity migration for crop_declarations:

1. Telegram + migrated schema  → platform id goes to sender_id, channel='telegram',
   phone stays NULL (no fabricated mobile number), dedup targets the partial
   sender index, and a genuine area update rewrites the matched row in place
   (migrating legacy phone-keyed rows on touch).
2. Telegram + unmigrated schema → exactly the historic phone-keyed statement.
3. WhatsApp / web             → unaffected regardless of schema state.
4. The information_schema probe (True/False/magic/exception, caching).
5. Read paths survive phone IS NULL: admin listing, summary, and the internal
   farmer endpoint (which must also match sender_id for Telegram `mycrops`).
6. Live-PostgreSQL integration (skipped when no local DB): the actual migration
   DDL is idempotent and BOTH unique guarantees hold simultaneously.

Feature flags are pinned per test (project spec) for determinism.
"""
from __future__ import annotations

import datetime
import re
from datetime import timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from backend.routers import conversation as conv


# ── helpers ────────────────────────────────────────────────────────────────

def _pin(monkeypatch, value):
    monkeypatch.setattr(conv, "_IDENTITY_PIN", value)


def _make_db(existing_declaration=None):
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = existing_declaration
    db.execute = AsyncMock(return_value=result_mock)
    return db


def _make_declaration(age_seconds=3600, id_=77, phone="1534422727", sender_id=None):
    return SimpleNamespace(
        id=id_, phone=phone, sender_id=sender_id, area_acres=1.0,
        declared_at=datetime.datetime.now(timezone.utc) - datetime.timedelta(seconds=age_seconds),
        crop="Tomato", district="Kolar",
    )


def _sat_patch():
    mock = AsyncMock()
    mock.return_value = {"saturation_pct": 10.0, "risk_level": "LOW",
                         "risk_kannada": "ಕಡಿಮೆ", "farmer_count": 1}
    return patch("backend.services.farmer_service.calc_saturation", new=mock)


def _compile(stmt):
    return str(stmt.compile(dialect=postgresql.dialect()))


def _compiled(stmt):
    comp = stmt.compile(dialect=postgresql.dialect())
    return str(comp), comp.construct_params()


# ── 1. Telegram on a migrated schema ───────────────────────────────────────

class TestTelegramIdentityMode:

    @pytest.mark.asyncio
    async def test_new_declaration_stores_sender_id_not_phone(self, monkeypatch):
        """First declaration: INSERT carries phone=NULL, channel='telegram',
        sender_id=<telegram id>, and conflicts on the partial sender index."""
        _pin(monkeypatch, True)
        db = _make_db(existing_declaration=None)
        with _sat_patch():
            await conv._handle_declare(sender_id="1534422727", crop="Tomato",
                                       district="Kolar", area=2.0, db=db,
                                       channel="telegram")
        stmt = db.execute.await_args_list[1].args[0]
        sql, params = _compiled(stmt)
        assert params["phone"] is None, "must not fabricate a mobile number"
        assert params["channel"] == "telegram"
        assert params["sender_id"] == "1534422727"
        assert re.search(r"lower\([^)]*sender_id", sql) is not None
        assert "sender_id IS NOT NULL" in sql          # partial-index conflict target
        assert "ON CONFLICT" in sql

    @pytest.mark.asyncio
    async def test_area_update_rewrites_matched_row_and_migrates_identity(self, monkeypatch):
        """Prior (legacy phone-keyed) row older than the dedup window → UPDATE
        in place: area changes, identity moves to sender_id, phone → NULL."""
        _pin(monkeypatch, True)
        prior = _make_declaration(age_seconds=3600, id_=77)
        db = _make_db(existing_declaration=prior)
        with _sat_patch():
            result = await conv._handle_declare(sender_id="1534422727", crop="Tomato",
                                                district="Kolar", area=3.0, db=db,
                                                channel="telegram")
        assert result["is_update"] is True
        assert db.execute.await_count == 2             # SELECT + UPDATE (no INSERT)
        stmt = db.execute.await_args_list[1].args[0]
        sql, params = _compiled(stmt)
        assert sql.startswith("UPDATE crop_declarations")
        assert params["phone"] is None                 # identity migrates on touch
        assert params["sender_id"] == "1534422727"
        assert params["area_acres"] == 3.0
        assert 77 in params.values()                   # targeted by primary key

    @pytest.mark.asyncio
    async def test_reuse_lookup_matches_both_identity_shapes(self, monkeypatch):
        """The dedup SELECT must OR phone and sender_id once migrated, so a
        farmer's legacy rows are still found and not duplicated."""
        _pin(monkeypatch, True)
        db = _make_db(existing_declaration=None)
        with _sat_patch():
            await conv._handle_declare(sender_id="1534422727", crop="Tomato",
                                       district="Kolar", area=2.0, db=db,
                                       channel="telegram")
        select_stmt = db.execute.await_args_list[0].args[0]
        sql = _compile(select_stmt).lower()
        assert "phone = " in sql and "sender_id = " in sql
        assert " or " in sql.split("where", 1)[1]

    @pytest.mark.asyncio
    async def test_duplicate_within_window_writes_nothing(self, monkeypatch):
        _pin(monkeypatch, True)
        db = _make_db(existing_declaration=_make_declaration(age_seconds=5))
        with _sat_patch():
            await conv._handle_declare(sender_id="1534422727", crop="Tomato",
                                       district="Kolar", area=2.0, db=db,
                                       channel="telegram")
        # exactly one statement on this session: the dedup SELECT. No INSERT/UPDATE.
        assert db.execute.await_count == 1
        stmt = db.execute.await_args_list[0].args[0]
        assert _compile(stmt).strip().upper().startswith("SELECT")


# ── 2/3. Legacy mode & other channels ──────────────────────────────────────

class TestLegacyAndOtherChannels:

    @pytest.mark.asyncio
    async def test_telegram_unmigrated_schema_keeps_historic_statement(self, monkeypatch):
        _pin(monkeypatch, False)
        db = _make_db(existing_declaration=None)
        with _sat_patch():
            await conv._handle_declare(sender_id="1534422727", crop="Tomato",
                                       district="Kolar", area=2.0, db=db,
                                       channel="telegram")
        stmt = db.execute.await_args_list[1].args[0]
        sql, params = _compiled(stmt)
        assert params["phone"] == "1534422727"
        assert "sender_id" not in sql and "channel" not in sql
        assert re.search(r"lower\([^)]*phone", sql) is not None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("channel", ["whatsapp", "web"])
    async def test_non_telegram_channels_unchanged_on_migrated_schema(self, monkeypatch, channel):
        """Even with the new columns present, only Telegram switches identity
        shape; WhatsApp/web keep the phone-keyed upsert exactly as before."""
        _pin(monkeypatch, True)
        db = _make_db(existing_declaration=None)
        with _sat_patch():
            await conv._handle_declare(sender_id="9876543210", crop="Ragi",
                                       district="Dharwad", area=1.5, db=db,
                                       channel=channel)
        stmt = db.execute.await_args_list[1].args[0]
        sql, params = _compiled(stmt)
        assert params["phone"] == "9876543210"
        assert "sender_id" not in sql
        assert re.search(r"lower\([^)]*phone", sql) is not None


# ── 4. Schema probe ─────────────────────────────────────────────────────────

class TestIdentityProbe:

    @pytest.fixture(autouse=True)
    def _fresh_probe_state(self, monkeypatch):
        monkeypatch.setattr(conv, "_IDENTITY_PIN", None)
        monkeypatch.setattr(conv, "_IDENTITY_AUTO", None)
        monkeypatch.setattr(conv, "_IDENTITY_AUTO_AT", 0.0)

    @pytest.mark.asyncio
    async def test_probe_true_is_cached(self):
        db = AsyncMock()
        res = MagicMock(); res.scalar.return_value = True
        db.execute = AsyncMock(return_value=res)
        assert await conv._identity_columns_present(db) is True
        assert await conv._identity_columns_present(db) is True
        assert db.execute.await_count == 1             # cached after first probe

    @pytest.mark.asyncio
    async def test_probe_false_reprobes_after_ttl(self):
        db = AsyncMock()
        res = MagicMock(); res.scalar.return_value = False
        db.execute = AsyncMock(return_value=res)
        assert await conv._identity_columns_present(db) is False
        assert await conv._identity_columns_present(db) is False
        assert db.execute.await_count == 1             # still inside the 5-min TTL
        conv._IDENTITY_AUTO_AT = 0.0                   # force expiry
        assert await conv._identity_columns_present(db) is False
        assert db.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_probe_mocks_and_errors_default_to_legacy(self):
        magic = AsyncMock()                        # scalar() → MagicMock, not True
        assert await conv._identity_columns_present(magic) is False
        boom = AsyncMock()
        boom.execute = AsyncMock(side_effect=RuntimeError("no information_schema"))
        assert await conv._identity_columns_present(boom) is False


# ── 5. Read paths with phone = None ────────────────────────────────────────

def _decl_row(i, phone, channel="telegram", sender_id="1534422727"):
    return SimpleNamespace(
        id=i, farmer_name="Telegram Farmer", phone=phone, channel=channel,
        sender_id=sender_id, village="", district="Kolar", taluk=None,
        crop="Tomato", area_acres=2.0, season="kharif_2026", trust_score=0.85,
        satellite_status="pending",
        declared_at=datetime.datetime(2026, 10, 20, tzinfo=timezone.utc),
    )


class TestReadPathsNullPhone:

    @pytest.mark.asyncio
    async def test_admin_listing_serialises_null_phone(self):
        from backend.routers.farmers import get_declarations
        db = AsyncMock()
        res = MagicMock()
        res.scalars.return_value.all.return_value = [_decl_row(1, None), _decl_row(2, "9876543210")]
        db.execute = AsyncMock(return_value=res)
        out = await get_declarations(limit=10, db=db, current_user=MagicMock())
        assert out[0]["phone"] is None
        assert out[0]["channel"] == "telegram"
        assert out[0]["sender_id"] == "1534422727"
        assert out[1]["phone"] == "9876543210"

    @pytest.mark.asyncio
    async def test_summary_survives_null_phones(self):
        from backend.routers.farmers import summary
        db = AsyncMock()
        res = MagicMock()
        res.scalars.return_value.all.return_value = [
            _decl_row(1, None), _decl_row(2, None), _decl_row(3, "9876543210"),
        ]
        db.execute = AsyncMock(return_value=res)
        out = await summary(db=db)
        assert out["total_declarations"] == 3
        # NULL phones simply don't count as unique mobiles — no crash, no fake entries.
        assert out["total_farmers"] == 1

    @pytest.mark.asyncio
    async def test_internal_endpoint_matches_sender_id_for_telegram_ids(self, monkeypatch):
        """telegram_bot/handlers/mycrops.py queries /farmers/{telegram_id}/declarations;
        with phone now NULL the lookup must also match sender_id."""
        from backend.routers import farmers as fm
        monkeypatch.setattr(fm.settings, "secret_key", "unit-test-internal-secret")
        db = AsyncMock()
        res = MagicMock()
        res.scalars.return_value.all.return_value = [_decl_row(1, None)]
        db.execute = AsyncMock(return_value=res)
        out = await fm.farmer_declarations(
            phone="1534422727", caller_id="1534422727",
            x_internal_secret="unit-test-internal-secret", db=db)
        assert out["count"] == 1
        sql = _compile(db.execute.await_args_list[0].args[0]).lower()
        assert "sender_id" in sql and " or " in sql


# ── 6. Migration rollback safety (unit) ────────────────────────────────────

class TestRollbackSafety:

    @pytest.mark.asyncio
    async def test_rollback_refuses_when_null_phone_has_no_sender_id(self):
        from scripts.tools.migrate_channel_sender_id import rollback_migrations
        conn = AsyncMock()
        col_rows = MagicMock()
        col_rows.all.return_value = [("phone", "YES"), ("sender_id", "YES"), ("channel", "YES")]
        refuse = MagicMock(); refuse.scalar.return_value = 2
        conn.execute = AsyncMock(side_effect=[col_rows, refuse])
        with pytest.raises(SystemExit) as exc:
            await rollback_migrations(conn)
        assert "ROLLBACK REFUSED" in str(exc.value)

    @pytest.mark.asyncio
    async def test_rollback_noop_when_columns_absent(self):
        from scripts.tools.migrate_channel_sender_id import rollback_migrations
        conn = AsyncMock()
        col_rows = MagicMock()
        col_rows.all.return_value = [("phone", "NO")]
        conn.execute = AsyncMock(return_value=col_rows)
        await rollback_migrations(conn)          # must not raise, must not touch data
        assert conn.execute.await_count == 1


# ── 7. Live PostgreSQL integration (skipped when local DB absent) ──────────

SENDER = "2223334445"
TEST_CROP, TEST_DISTRICT, TEST_SEASON = "TestSplitCrop", "TestSplitDistrict", "test_split_2026"


@pytest.mark.asyncio
async def test_live_pg_migration_and_dual_uniqueness():
    """Applies the real migration DDL to the local PostgreSQL, proves BOTH the
    legacy phone unique index and the new partial sender index hold, then
    cleans up its own rows. Skipped when no local PostgreSQL is reachable."""
    pytest.importorskip("psycopg")
    from sqlalchemy import text as sa_text
    from sqlalchemy.exc import IntegrityError, OperationalError
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from backend.core.config import settings
    from backend.core.models import CropDeclaration
    from scripts.tools.migrate_channel_sender_id import apply_migrations

    engine = create_async_engine(settings.database_url)
    try:
        async with engine.connect() as c:
            await c.execute(sa_text("SELECT 1"))
    except (OperationalError, Exception):
        await engine.dispose()
        pytest.skip("local PostgreSQL not reachable")

    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await apply_migrations(conn)
            await apply_migrations(conn)           # idempotency: second run is a no-op

        async def _mk(session, **over):
            v = dict(farmer_name="identity-test", phone=None, channel="telegram",
                     sender_id=SENDER, village="", district=TEST_DISTRICT,
                     crop=TEST_CROP, area_acres=1.0, season=TEST_SEASON,
                     trust_score=0.5, satellite_status="pending")
            v.update(over)
            session.add(CropDeclaration(**v))
            await session.commit()

        # sender-keyed dedup enforced (new guarantee)
        async with Session() as s:
            await _mk(s)
        with pytest.raises(IntegrityError):
            async with Session() as s:
                await _mk(s)

        # legacy phone-keyed dedup still enforced for phone rows (old guarantee)
        legacy_phone = "9112223334"
        async with Session() as s:
            s.add(CropDeclaration(farmer_name="identity-test", phone=legacy_phone,
                                  village="", district=TEST_DISTRICT, crop=TEST_CROP,
                                  area_acres=1.0, season="legacy_season_2026",
                                  trust_score=0.5, satellite_status="pending"))
            await s.commit()
        with pytest.raises(IntegrityError):
            async with Session() as s:
                s.add(CropDeclaration(farmer_name="identity-test", phone=legacy_phone,
                                      village="", district=TEST_DISTRICT, crop=TEST_CROP,
                                      area_acres=2.0, season="legacy_season_2026",
                                      trust_score=0.5, satellite_status="pending"))
                await s.commit()

        # NULL-phone rows are invisible to the phone index (proves why the
        # partial sender index is required) and a different season is allowed
        async with Session() as s:
            await _mk(s, season="other_season_2027")
    finally:
        async with engine.begin() as conn:
            await conn.execute(sa_text(
                "DELETE FROM crop_declarations WHERE sender_id = :x OR phone IN "
                "('9112223334')"), {"x": SENDER})
        await engine.dispose()
