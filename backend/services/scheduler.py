"""
backend/services/scheduler.py — periodic AGMARKNET refresh

Runs inside the API process as an asyncio task. Two properties matter:

* Only one refresh runs at a time across all Uvicorn workers, enforced by the
  PostgreSQL advisory lock in `data_refresh.refresh_lock`. A worker that loses
  the race skips its turn instead of stacking a duplicate fetch.
* A refresh failure never propagates. The scheduler logs, records the failed
  run, and retries on the next tick — an exception escaping here would take the
  API down for a data-ingestion problem.

For a deployment that prefers an external timer, `scripts/refresh_prices.py`
exposes the same pipeline as a CLI and can be driven by cron or a systemd
timer; `REFRESH_ENABLED=false` turns this in-process loop off.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.core.config import settings
from backend.core.database import AsyncSessionLocal, engine
from backend.services import data_refresh

logger = logging.getLogger("kisanmitra.scheduler")


async def refresh_once(*, trigger: str = "scheduler", **kwargs) -> dict[str, Any] | None:
    """
    One refresh, serialised against every other worker.

    Returns the run summary, or None when another process already holds the
    lock — "someone else is on it" is a normal outcome, not an error.
    """
    try:
        async with data_refresh.refresh_lock(engine):
            async with AsyncSessionLocal() as db:
                return await data_refresh.run_refresh(db, trigger=trigger, **kwargs)
    except data_refresh.RefreshAlreadyRunning:
        logger.info("refresh skipped — another worker holds the lock")
        return None
    except Exception:  # noqa: BLE001
        logger.exception("refresh failed outside the pipeline")
        return None


async def is_stale() -> bool:
    """True when the feed cannot currently support a forecast."""
    try:
        async with AsyncSessionLocal() as db:
            health = await data_refresh.data_freshness(db)
        return not health["forecastable"]
    except Exception:  # noqa: BLE001
        logger.exception("could not read feed freshness")
        return False


async def refresh_loop(
    interval_hours: float | None = None,
    *,
    catch_up_on_start: bool = True,
) -> None:
    """
    Sleep, refresh, repeat.

    On start it refreshes immediately only if the feed is already past the
    freshness SLA — that is the recovery path after an outage or a deploy that
    was offline for a day. A healthy feed waits its full interval instead of
    spending API quota on every restart.
    """
    interval = (interval_hours if interval_hours is not None
                else settings.refresh_interval_hours) * 3600.0

    logger.info("AGMARKNET refresh scheduler started (every %.1f h)", interval / 3600.0)
    try:
        while True:
            if catch_up_on_start and await is_stale():
                logger.info("feed is past the %s-day SLA — refreshing now",
                            settings.price_max_age_days)
                await refresh_once(trigger="startup")
            catch_up_on_start = False
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.info("AGMARKNET refresh scheduler stopped")
        raise


def start_refresh_task() -> asyncio.Task | None:
    """Spawn the scheduler on the running loop. No-op when disabled."""
    if not settings.refresh_enabled:
        logger.info("refresh scheduler disabled (REFRESH_ENABLED=false)")
        return None
    task = asyncio.get_running_loop().create_task(
        refresh_loop(), name="agmarknet-refresh-loop"
    )
    logger.info("AGMARKNET refresh scheduler task created")
    return task


async def stop_refresh_task(task: asyncio.Task | None) -> None:
    """Cancel and await the scheduler so shutdown does not orphan a fetch."""
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
