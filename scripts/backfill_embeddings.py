#!/usr/bin/env python3
"""
scripts/backfill_embeddings.py

Re-embeds existing knowledge_chunks rows with the canonical query-time
embedding model (backend.services.rag.embed_text) so that EVERY vector in
the pgvector column lives in the same semantic space as query vectors.

Why this exists:
    Rows seeded before the vector-retrieval fix were embedded with a
    different model than query-time retrieval uses. pgvector cannot tell
    you which model produced a stored vector, so cosine distances against
    mixed-space vectors are meaningless. The safe default is to re-embed
    ALL rows (--only-missing restricts to rows with NULL embeddings).

Usage:
    PYTHONPATH=. python scripts/backfill_embeddings.py                  # re-embed everything
    PYTHONPATH=. python scripts/backfill_embeddings.py --only-missing   # fill NULLs only
    PYTHONPATH=. python scripts/backfill_embeddings.py --dry-run        # probe + count, no writes
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Allow importing backend modules from the project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from backend.core.config import settings

EMBEDDING_DIM = 768   # must match Vector(768) in backend/core/models.py


async def probe(engine) -> tuple[bool, str]:
    """Return (vector_extension_installed, live udt_name of knowledge_chunks.embedding)."""
    async with engine.connect() as conn:
        ext = await conn.execute(
            sa.text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        )
        installed = ext.scalar() is not None
        col = await conn.execute(
            sa.text(
                "SELECT a.atttypid::regtype::text "
                "FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
                "WHERE c.relname = 'knowledge_chunks' AND a.attname = 'embedding'"
            )
        )
        col_type = col.scalar() or "<table/column missing>"
    return installed, col_type


async def embed_with_retry(embed_text, text: str, max_attempts: int = 3) -> list[float] | None:
    """embed_text() swallows errors and returns None — retry that signal explicitly."""
    for attempt in range(max_attempts):
        vector = await embed_text(text)
        if vector is not None:
            return vector
        wait = 2 ** attempt
        print(f"   ⚠️ Embedding failed (attempt {attempt + 1}/{max_attempts}). Retrying in {wait}s...")
        await asyncio.sleep(wait)
    return None


async def main(dry_run: bool, only_missing: bool, batch_size: int) -> None:
    engine = create_async_engine(settings.database_url, echo=False)

    # ── 1. Probe live database state (before any ORM import — models.py
    #       reads DB_HAS_PGVECTOR at import time to choose column types) ──
    installed, col_type = await probe(engine)
    print(f"\n── Probing database ──")
    print(f"   vector extension: {'✓ installed' if installed else '✗ NOT installed'}")
    print(f"   knowledge_chunks.embedding column type: {col_type}")

    if not installed:
        print("\n❌ pgvector is not installed in this database — vector retrieval is impossible.")
        print("   Install it (CREATE EXTENSION vector) or run scripts/00_init_db.py on a server with pgvector.")
        await engine.dispose()
        sys.exit(1)

    if col_type.lower() != "vector":
        if dry_run:
            print(f"\n⚠️  embedding column is '{col_type}', not 'vector'. A real run would migrate it.")
        else:
            print(f"\n── Migrating embedding column: {col_type} → vector({EMBEDDING_DIM}) ──")
            print("   (existing text values are dropped — they were never valid single-space vectors)")
            async with engine.begin() as conn:
                await conn.execute(sa.text(
                    f"ALTER TABLE knowledge_chunks "
                    f"ALTER COLUMN embedding TYPE vector({EMBEDDING_DIM}) USING NULL"
                ))
            print("   Column migrated ✓")
        if not dry_run:
            installed, col_type = await probe(engine)

    # Tell models.py to build the ORM in pgvector mode BEFORE importing it.
    os.environ["DB_HAS_PGVECTOR"] = "1"

    from backend.core.models import KnowledgeChunk          # noqa: E402
    from backend.services import rag as rag_service         # noqa: E402
    embed_text = rag_service.embed_text

    if rag_service._embeddings is None:
        print("\n❌ GEMINI_API_KEY missing/invalid — embeddings model not initialized.")
        print("   Set GEMINI_API_KEY in .env before backfilling (every row would fail otherwise).")
        await engine.dispose()
        sys.exit(1)

    # ── 2. Select rows to re-embed ──
    from sqlalchemy import select                          # noqa: E402
    async with engine.connect() as conn:
        total = (await conn.execute(sa.text("SELECT count(*) FROM knowledge_chunks"))).scalar()
    where_clause = "WHERE embedding IS NULL" if only_missing else ""
    async with engine.connect() as conn:
        target = (await conn.execute(
            sa.text(f"SELECT count(*) FROM knowledge_chunks {where_clause}")
        )).scalar()

    print(f"\n── Backfill plan ──")
    print(f"   Rows in knowledge_chunks : {total}")
    print(f"   Rows to re-embed         : {target} ({'NULL embeddings only' if only_missing else 'ALL rows — mixed model space'})")

    if dry_run:
        print("\n🔍 Dry run complete — no writes performed.")
        await engine.dispose()
        return

    if target == 0:
        print("\n✅ Nothing to do.")
        await engine.dispose()
        return

    # ── 3. Re-embed row by row, commit in batches ──
    from backend.core.database import AsyncSessionLocal    # noqa: E402

    done = failed = 0
    async with AsyncSessionLocal() as session:
        stmt = select(KnowledgeChunk.id, KnowledgeChunk.content, KnowledgeChunk.crop)
        if only_missing:
            stmt = stmt.where(KnowledgeChunk.embedding.is_(None))
        rows = (await session.execute(stmt)).all()

        for row in rows:
            vector = await embed_with_retry(embed_text, row.content)
            if vector is None:
                print(f"   ❌ id={row.id} [{row.crop}] — giving up after retries (embedding unavailable)")
                failed += 1
                continue
            if len(vector) != EMBEDDING_DIM:
                print(f"   ❌ id={row.id} — model returned {len(vector)} dims, expected {EMBEDDING_DIM}. Skipping.")
                failed += 1
                continue
            await session.execute(
                # CAST() form, not ':vec::vector': psycopg3 renders :name as
                # %(name)s and the chained :: cast breaks text() parsing.
                sa.text("UPDATE knowledge_chunks SET embedding = CAST(:vec AS vector) WHERE id = :id"),
                {"vec": str(vector), "id": row.id},
            )
            done += 1
            if done % batch_size == 0:
                await session.commit()
                print(f"   💾 {done}/{len(rows)} embedded & committed")
            await asyncio.sleep(0.15)  # be gentle on the embedding API rate limit

        await session.commit()

    await engine.dispose()
    print(f"\n✅ Backfill complete: {done} re-embedded, {failed} failed.")
    print("   Query-time cosine ranking now operates on a single consistent embedding space.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only-missing", action="store_true",
                        help="embed only rows with NULL embeddings instead of re-embedding all rows")
    parser.add_argument("--dry-run", action="store_true",
                        help="probe extension/column state and count target rows without writing")
    parser.add_argument("--batch-size", type=int, default=20,
                        help="commit interval (default 20)")
    args = parser.parse_args()
    asyncio.run(main(args.dry_run, args.only_missing, args.batch_size))
