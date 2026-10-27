#!/usr/bin/env python
"""KisanMitra market-data freshness check (read-only, no secrets printed).

Resolves the DB target from the environment the same way the backend does:
individual DB_* vars win; otherwise the Neon direct endpoint is parsed out of
DATABASE_URL_UNPOOLED in .env. Prints one verdict line and exits 0 (fresh) or
1 (stale / unreachable) so cron, systemd timers or a human can act on it.

Usage:  ./venv/bin/python scripts/tools/check_freshness.py [--max-age 3]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _apply_neon_env() -> None:
    """Point DB_* at Neon if the caller did not already provide a remote host."""
    if os.environ.get("DB_HOST") and os.environ["DB_HOST"] != "localhost":
        return
    env_file = ROOT / ".env"
    url = None
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("DATABASE_URL_UNPOOLED="):
                url = line.split("=", 1)[1].strip().strip('"')
    if not url:
        return  # fall through to whatever DB_* defaults exist
    m = re.match(
        r"postgres(?:ql)?://([^:]+):([^@]*)@([^/?]+)(?::(\d+))?/([^?]+)", url
    )
    if not m:
        print(f"FAIL: cannot parse DATABASE_URL_UNPOOLED ({len(url)} chars)")
        sys.exit(1)
    os.environ.update(
        DB_HOST=m.group(3), DB_PORT=m.group(4) or "5432", DB_NAME=m.group(5),
        DB_USER=m.group(1), DB_PASSWORD=m.group(2),
        DB_SSLMODE="require", DB_HAS_PGVECTOR="1",
    )


async def _check(max_age_days: int) -> int:
    _apply_neon_env()
    sys.path.insert(0, str(ROOT))
    from sqlalchemy import text
    from backend.core.config import settings
    from backend.core.database import AsyncSessionLocal

    if settings.db_host in ("", "localhost"):
        print("FAIL: DB target is local — expected Neon endpoint")
        return 1
    async with AsyncSessionLocal() as db:
        row = (await db.execute(text(
            "select max(arrival_date)::date, count(*) from mandi_prices"
        ))).one()
        newest, total = row
        run = (await db.execute(text(
            "select status, rows_inserted, finished_at from data_refresh_runs "
            "order by id desc limit 1"
        ))).one_or_none()
    age = (datetime.now(timezone.utc).date() - newest).days if newest else None
    run_txt = (f"last run {run[0]} (+{run[1]} rows @ "
               f"{run[2]:%d/%m %H:%M} UTC)" if run and run[2] else "no run logged")
    ok = newest is not None and age <= max_age_days
    print(f"{'FRESH' if ok else 'STALE'}: newest market date {newest} "
          f"({age}d old, limit {max_age_days}d), {total} rows, {run_txt}, "
          f"host={settings.db_host.split('.')[0]}")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-age", type=int, default=3,
                    help="max acceptable age of newest arrival_date in days")
    args = ap.parse_args()
    try:
        sys.exit(asyncio.run(_check(args.max_age)))
    except Exception as e:  # fail loudly but never leak config values
        print(f"FAIL: {type(e).__name__}: {str(e)[:160]}")
        sys.exit(1)
