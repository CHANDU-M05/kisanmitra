"""
scripts/refresh_prices.py — AGMARKNET refresh from cron / systemd / a shell

Same pipeline the in-process scheduler uses (`backend.services.data_refresh`),
reachable without the API running. Useful either as the primary trigger
(REFRESH_ENABLED=false plus a systemd timer) or as a manual "catch up now".

Exit codes are deliberately distinct, because a cron entry needs to alert on a
failure and stay quiet when the mandi simply has not published anything new:

    0  success          new rows landed
    0  no_new_data      upstream published nothing newer (not an error)
    1  failed           fetch / parse / write problem
    3  already running  another refresh holds the lock
    4  configuration    no API key — nothing could have worked

Usage:
    python scripts/refresh_prices.py
    python scripts/refresh_prices.py --lookback-days 3 --crops Tomato,Onion
    python scripts/refresh_prices.py --json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from backend.core.config import settings          # noqa: E402
from backend.core.database import AsyncSessionLocal, engine  # noqa: E402
from backend.services import data_refresh          # noqa: E402


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh AGMARKNET mandi prices")
    parser.add_argument("--lookback-days", type=int, default=None,
                        help=f"window to fetch (default {settings.refresh_lookback_days})")
    parser.add_argument("--crops", default=None,
                        help="comma-separated crop list (default all mapped crops)")
    parser.add_argument("--json", action="store_true", help="emit the summary as JSON")
    args = parser.parse_args(argv)

    if not settings.data_gov_api_key:
        print("DATA_GOV_API_KEY is not set — cannot refresh.", file=sys.stderr)
        return 4

    crops = [c.strip() for c in args.crops.split(",")] if args.crops else None

    # Standalone runs must not assume the API already created the schema.
    import importlib
    init_db = importlib.import_module("scripts.00_init_db").init_db
    await init_db()

    try:
        async with data_refresh.refresh_lock(engine):
            async with AsyncSessionLocal() as db:
                summary = await data_refresh.run_refresh(
                    db, trigger="cli", crops=crops,
                    lookback_days=args.lookback_days,
                )
    except data_refresh.RefreshAlreadyRunning:
        print("Another refresh is already running.", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print(f"status          : {summary['status']}")
        print(f"window          : {summary['window_start']} → {summary['window_end']}")
        print(f"fetched         : {summary['rows_fetched']}")
        print(f"validated       : {summary['rows_validated']}")
        print(f"duplicates      : {summary['rows_duplicate']}")
        print(f"rejected        : {summary['rows_rejected']}  {summary['rejection_reasons']}")
        print(f"inserted        : {summary['rows_inserted']}")
        print(f"db newest (before): {summary['prev_newest_date']}")
        print(f"upstream newest : {summary['upstream_newest_date']}")
        if summary["error"]:
            print(f"error           : {summary['error']}")

    async with AsyncSessionLocal() as db:
        health = await data_refresh.data_freshness(db)
    print(f"feed age        : {health['age_days']} days "
          f"(SLA {health['max_age_days']}) — "
          f"{'forecasts available' if health['forecastable'] else 'forecasts still blocked'}")

    await engine.dispose()
    return 0 if summary["status"] in ("success", "no_new_data") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
