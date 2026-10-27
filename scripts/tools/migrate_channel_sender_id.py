"""
scripts/tools/migrate_channel_sender_id.py — crop_declarations identity columns (Phase 1).

Adds nullable identity columns so platform sender ids stop living in `phone`:

    ALTER TABLE crop_declarations ADD COLUMN channel   VARCHAR(20);
    ALTER TABLE crop_declarations ADD COLUMN sender_id VARCHAR(64);
    ALTER TABLE crop_declarations ALTER COLUMN phone DROP NOT NULL;
    CREATE UNIQUE INDEX uq_decl_sender_crop_district_season
        ON crop_declarations (lower(sender_id), lower(crop), lower(district), season)
        WHERE sender_id IS NOT NULL;

Design decisions (verified against live schema before writing):
  * The existing unique index uq_decl_phone_crop_district_season is kept UNTOUCHED.
    It still guards every phone-bearing row (web/WhatsApp/legacy). The new partial
    unique index only covers sender_id-bearing rows; because Postgres treats NULLs
    as distinct in unique indexes, sender-keyed rows would otherwise have NO
    database-level duplicate protection, silently weakening current guarantees.
  * NO historical backfill / classification. Legacy rows cannot be attributed to a
    platform reliably (no provenance column was ever stored), so they are left
    explicitly unclassified: channel/sender_id stay NULL. Classification by phone
    pattern or farmer_name is forbidden — it guesses.
  * Deliberately NOT wired into scripts/00_init_db.py: that module runs on every
    app startup (backend/main.py _bootstrap_database), and this migration must be
    an operator decision with a backup first. Deploy ordering is strict:
        backup  →  --apply  →  verify  →  deploy code that maps the new columns.
    The app's information_schema probe (conversation._identity_columns_present)
    makes the code itself safe on either schema state, but ORM reads require the
    migration to precede the deploy.

Rollback (--rollback) restores the pre-migration shape:
    UPDATE crop_declarations SET phone = sender_id WHERE phone IS NULL;  -- re-seed ids
    ALTER TABLE ... ALTER COLUMN phone SET NOT NULL;                     -- aborts if unsafe
    DROP INDEX  uq_decl_sender_crop_district_season;
    ALTER TABLE ... DROP COLUMN sender_id, DROP COLUMN channel;
Rollback is only exercised while no phone-NULL row lacks a sender_id (guaranteed
by the write path); the script refuses otherwise.

Usage (Neon: use the direct/unpooled URL, never prints credentials):
    python -m scripts.tools.migrate_channel_sender_id --apply
    python -m scripts.tools.migrate_channel_sender_id --rollback
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from backend.core.config import settings

# Distinct from init_db's 888999 so the two never block each other silently.
_ADVISORY_LOCK_ID = 889001

APPLY_STATEMENTS = [
    "ALTER TABLE crop_declarations ADD COLUMN IF NOT EXISTS channel VARCHAR(20)",
    "ALTER TABLE crop_declarations ADD COLUMN IF NOT EXISTS sender_id VARCHAR(64)",
    "ALTER TABLE crop_declarations ALTER COLUMN phone DROP NOT NULL",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_decl_sender_crop_district_season
       ON crop_declarations (lower(sender_id), lower(crop), lower(district), season)
       WHERE sender_id IS NOT NULL""",
]


async def apply_migrations(conn) -> None:
    """Idempotent: safe to re-run; each statement is a no-op once applied."""
    for sql in APPLY_STATEMENTS:
        await conn.execute(text(sql))


async def _column_state(conn) -> dict:
    rows = (await conn.execute(text(
        "SELECT column_name, is_nullable FROM information_schema.columns "
        "WHERE table_name = 'crop_declarations' AND table_schema = current_schema()"
    ))).all()
    return {name: nullable for name, nullable in rows}


async def rollback_migrations(conn) -> None:
    """Restore the pre-migration schema. Refuses if any phone-NULL row has no
    sender_id to re-seed from (re-adding NOT NULL would silently drop data)."""
    state = await _column_state(conn)
    if "sender_id" not in state:
        print("   nothing to roll back (columns absent) — already legacy schema")
        return
    null_without_sender = (await conn.execute(text(
        "SELECT count(*) FROM crop_declarations "
        "WHERE phone IS NULL AND (sender_id IS NULL OR sender_id = '')"
    ))).scalar()
    if null_without_sender:
        raise SystemExit(
            f"ROLLBACK REFUSED: {null_without_sender} row(s) have phone NULL and no "
            "sender_id to re-seed from. Fix those rows first; refusing to lose data."
        )
    await conn.execute(text(
        "UPDATE crop_declarations SET phone = sender_id "
        "WHERE phone IS NULL AND sender_id IS NOT NULL"
    ))
    await conn.execute(text(
        "DROP INDEX IF EXISTS uq_decl_sender_crop_district_season"))
    await conn.execute(text(
        "ALTER TABLE crop_declarations ALTER COLUMN phone SET NOT NULL"))
    await conn.execute(text(
        "ALTER TABLE crop_declarations DROP COLUMN IF EXISTS sender_id"))
    await conn.execute(text(
        "ALTER TABLE crop_declarations DROP COLUMN IF EXISTS channel"))


async def run(mode: str, database_url: str) -> None:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            locked = (await conn.execute(
                text(f"SELECT pg_try_advisory_lock({_ADVISORY_LOCK_ID})"))).scalar()
            if not locked:
                raise SystemExit("Another migration holds the advisory lock; retry later.")
            try:
                total = (await conn.execute(text(
                    "SELECT count(*) FROM crop_declarations"))).scalar()
                if mode == "apply":
                    await apply_migrations(conn)
                    state = await _column_state(conn)
                    idx = (await conn.execute(text(
                        "SELECT count(*) FROM pg_indexes WHERE indexname = "
                        "'uq_decl_sender_crop_district_season'"))).scalar()
                    print(f"APPLIED. rows={total} "
                          f"channel={'OK' if 'channel' in state else 'MISSING'} "
                          f"sender_id={'OK' if 'sender_id' in state else 'MISSING'} "
                          f"phone_nullable={state.get('phone', '?')=='YES'} "
                          f"sender_index={'OK' if idx else 'MISSING'}")
                else:
                    await rollback_migrations(conn)
                    state = await _column_state(conn)
                    print(f"ROLLED BACK. rows={total} "
                          f"phone_nullable={state.get('phone', '?')=='YES'} "
                          f"channel_still_present={'channel' in state}")
            finally:
                await conn.execute(text(f"SELECT pg_advisory_unlock({_ADVISORY_LOCK_ID})"))
    finally:
        await engine.dispose()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--apply", action="store_true", help="add identity columns/index")
    group.add_argument("--rollback", action="store_true", help="restore pre-migration schema")
    p.add_argument("--database-url", default=None,
                   help="override; defaults to settings.database_url. For Neon run "
                        "with DATABASE_URL_UNPOOLED (asyncpg/psycopg scheme required).")
    args = p.parse_args()

    url = args.database_url or os.environ.get("MIGRATION_DATABASE_URL") or settings.database_url
    # never echo the URL — it embeds credentials
    host = re.sub(r"://[^@]*@", "://***@", url)
    print(f"target host: {host[:60]}")
    asyncio.run(run("apply" if args.apply else "rollback", url))


if __name__ == "__main__":
    sys.exit(main())
