"""
backend/services/scheduler.py — periodic AGMARKNET refresh

Runs inside the API process as an asyncio task. Two properties matter:

* Only one refresh runs at a time across all Uvicorn workers, enforced by the
  PostgreSQL advisory lock in `data_refresh.refresh_lock`. A worker that loses
  the race skips its turn instead of stacking a duplicate fetch.
* A refresh failure never propagates. `refresh_once` classifies every attempt
  as done/locked/failed and logs the rest: an exception escaping here would
  take the API down for a data-ingestion problem. The loop's startup catch-up
  retries failures with a bounded, exponential backoff, and scheduled ticks
  keep trying on the ordinary cadence afterwards.

For a deployment that prefers an external timer, `scripts/refresh_prices.py`
exposes the same pipeline as a CLI and can be driven by cron or a systemd
timer; `REFRESH_ENABLED=false` turns this in-process loop off.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from backend.core.config import redact_secrets, settings
from backend.core.database import AsyncSessionLocal, engine
from backend.services import data_refresh
from backend.services.freshness import FRESHNESS, FreshnessState

logger = logging.getLogger("kisanmitra.scheduler")

# refresh_once(detailed=True) outcomes. "locked" is CONTENTION — another
# worker owns the refresh and is doing the work — so it must never be
# retried in a tight loop nor counted as a failure.
REFRESH_DONE = "refreshed"
REFRESH_LOCKED = "locked"
REFRESH_FAILED = "failed"

# Bounded startup catch-up (A2). After an outage or a day-long deploy gap the
# first thing a worker does is try to bring the feed back, at most this many
# times with exponential backoff between attempts. Bounded on purpose: a
# persistent failure is an operator problem, not something to hammer the
# upstream or the database about; the ordinary scheduled tick keeps trying on
# its own cadence afterwards.
STARTUP_CATCHUP_MAX_ATTEMPTS = 3
STARTUP_CATCHUP_BACKOFF_SECONDS = 30.0

# Pipeline statuses that genuinely mean the attempt succeeded, read from
# run_refresh itself: "success" (rows processed, insertions or a documented
# newest-after state) and "no_new_data" (the window was fetched and
# validated but the upstream had published nothing new — a working pipeline,
# not a failed one). EVERYTHING ELSE — "failed", a missing or malformed
# summary, or any unknown status — is REFRESH_FAILED. run_refresh catches
# pipeline exceptions internally and *returns* status="failed", so trusting
# "it returned without raising" would count real ingestion failures as
# recovery (review D1).
REFRESH_SUCCESS_STATUSES = frozenset({"success", "no_new_data"})


async def refresh_once(
    *, trigger: str = "scheduler", detailed: bool = False, **kwargs
) -> dict[str, Any] | None | tuple[str, dict[str, Any] | None]:
    """
    One refresh, serialised against every other worker.

    Compatibility contract: without ``detailed`` this returns the run
    summary, or None when the refresh was skipped (lock held) or failed —
    the long-standing shape existing callers and tests pin. With
    ``detailed=True`` the caller gets ``(outcome, summary)`` so the
    scheduler can tell success from contention from failure instead of
    treating two very different Nones alike.

    A refresh attempt maintains the shared freshness snapshot whatever its
    outcome (review D2/D3): ingestion changing the feed must not leave a
    cached verdict describing the old state; a FAILED attempt is exactly the
    case where the database may have gone away and the stale FRESH claim must
    be invalidated; and a worker that LOSES the advisory-lock race still
    needs to re-read what the winner committed, or its own /health cache
    silently ages to UNAVAILABLE on a perfectly healthy feed. The snapshot
    update can never change the classified outcome — a maintenance failure
    leaves a failed refresh failed.
    """
    summary: dict[str, Any] | None = None
    outcome = REFRESH_FAILED
    try:
        async with data_refresh.refresh_lock(engine):
            async with AsyncSessionLocal() as db:
                summary = await data_refresh.run_refresh(db, trigger=trigger, **kwargs)
        status = summary.get("status") if isinstance(summary, dict) else None
        if status in REFRESH_SUCCESS_STATUSES:
            outcome = REFRESH_DONE
        else:
            outcome = REFRESH_FAILED
            logger.warning(
                "refresh attempt ended with status=%s — classified as failed",
                status if status is not None else repr(summary)[:80],
            )
    except data_refresh.RefreshAlreadyRunning:
        logger.info("refresh skipped — another worker holds the lock")
        outcome = REFRESH_LOCKED
    except Exception:  # noqa: BLE001
        logger.exception("refresh failed outside the pipeline")
        outcome = REFRESH_FAILED

    try:
        await FRESHNESS.refresh(AsyncSessionLocal)
    except Exception:  # noqa: BLE001 — cache maintenance cannot break a refresh
        logger.warning("freshness snapshot maintenance after refresh attempt "
                       "(%s) failed", outcome, exc_info=True)

    if detailed:
        return outcome, summary
    return summary


async def is_stale() -> bool:
    """
    True when the feed cannot currently support a forecast.

    FAIL CLOSED (A2): this used to return False when the freshness query
    itself raised, which read a database outage as "the feed is current" and
    let the startup catch-up skip the one recovery refresh that could have
    helped. Anything that is not provably FRESH — stale, empty, or simply
    unknown — returns True so the caller attempts a bounded recovery
    without ever claiming the feed is fine.

    Reads through the shared FRESHNESS cache so the verdict and the health
    endpoint can never disagree.
    """
    snapshot = await FRESHNESS.refresh(AsyncSessionLocal)
    return snapshot.state is not FreshnessState.FRESH


async def _startup_catch_up(*, sleep: Callable[[float], Any] | None = None) -> None:
    """
    Bounded recovery refresh at startup: at most STARTUP_CATCHUP_MAX_ATTEMPTS
    attempts with exponential backoff between them.

    Stops early and correctly on each distinct outcome:
      * not stale (including UNAVAILABLE→probe→FRESH) — nothing to do;
      * REFRESH_DONE — the feed was brought back;
      * REFRESH_LOCKED — another worker owns the refresh; that is success by
        delegation, retrying would just duplicate its turn.
    Only REFRESH_FAILED consumes an attempt. The final outcome is logged
    either way so an operator can see whether startup recovered or gave up.
    """
    sleep_fn = sleep or asyncio.sleep
    for attempt in range(1, STARTUP_CATCHUP_MAX_ATTEMPTS + 1):
        if not await is_stale():
            logger.info("startup catch-up: feed is current, no refresh needed")
            return
        logger.info(
            "startup catch-up attempt %d/%d — feed is not provably fresh",
            attempt, STARTUP_CATCHUP_MAX_ATTEMPTS,
        )
        res = await refresh_once(trigger="startup", detailed=True)
        # Defensive unpacking: a patched-out refresh_once may return the
        # legacy summary/None shape instead of the detailed tuple.
        if isinstance(res, tuple):
            outcome, _summary = res
        else:
            outcome = REFRESH_DONE if res else REFRESH_FAILED
        if outcome == REFRESH_DONE:
            logger.info("startup catch-up: refresh completed")
            return
        if outcome == REFRESH_LOCKED:
            logger.info(
                "startup catch-up: another worker holds the refresh lock — "
                "not retrying (that worker owns this recovery)"
            )
            return
        # REFRESH_FAILED: a failed refresh is NOT a recovery; try again,
        # bounded, with backoff — unless attempts are spent.
        if attempt < STARTUP_CATCHUP_MAX_ATTEMPTS:
            backoff = STARTUP_CATCHUP_BACKOFF_SECONDS * (2 ** (attempt - 1))
            logger.warning(
                "startup catch-up attempt %d failed — retrying in %.0fs",
                attempt, backoff,
            )
            await sleep_fn(backoff)
    logger.error(
        "startup catch-up gave up after %d attempts; feed remains %s — "
        "scheduled ticks will keep trying",
        STARTUP_CATCHUP_MAX_ATTEMPTS,
        FRESHNESS.get().state.value,
    )


async def refresh_loop(
    interval_hours: float | None = None,
    *,
    catch_up_on_start: bool = True,
) -> None:
    """
    Sleep, refresh, repeat.

    The first tick runs the bounded startup catch-up (immediate refresh only
    when the feed is not provably fresh — the recovery path after an outage
    or a deploy that was offline for a day). Every later tick runs a
    scheduled refresh: the pre-A2 loop set its catch-up flag False after the
    first iteration and then only ever slept, so a long-lived process never
    ingested again until it was restarted. That silently defeated the whole
    freshness SLA and is corrected here. A healthy feed still costs one
    locked, idempotent pipeline per interval — the advisory lock makes
    overlapping worker ticks harmless.
    """
    interval = (interval_hours if interval_hours is not None
                else settings.refresh_interval_hours) * 3600.0

    logger.info("AGMARKNET refresh scheduler started (every %.1f h)", interval / 3600.0)
    first = True
    try:
        while True:
            if first and catch_up_on_start:
                await _startup_catch_up()
            else:
                await refresh_once(trigger="scheduled")
            first = False
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


# ── Independent freshness monitor (A2 fix round) ────────────────────
#
# /health answers from the cached snapshot, so the cache needs an owner that
# keeps it current even when THIS process does not own ingestion: the shipped
# deployment refreshes via an external systemd timer with REFRESH_ENABLED=
# false, in which case the refresh scheduler — and with it every cache update
# — never starts, and a long-lived worker would serve its startup verdict
# until the TTL expired and then sit at UNAVAILABLE while cron kept the feed
# perfectly fresh. Shortening the TTL is not monitoring: it makes health
# confidently wrong faster instead of checking.
#
# This task is the answer to "is the application's picture of the feed
# still true?" and nothing else. It runs the same read-only
# compute_freshness the rest of the system trusts (never the ingest lock,
# never run_refresh, never a write), it updates only this worker's own
# snapshot, and it coexists with the refresh scheduler — when ingestion runs
# in-process, refresh_once already re-reads after every attempt, so the
# monitor is a low-cost safety net for the gaps between ticks (and the only
# signal at all when ingestion is external). One task per process; starting
# it twice is a no-op by design.

_freshness_monitor_task: asyncio.Task | None = None


async def freshness_monitor_loop() -> None:
    """
    Re-read feed freshness every ``freshness_check_interval_seconds``.

    Sleep-first: startup already warmed the snapshot in the lifespan, so an
    immediate recheck would only duplicate that query. The sleep is directly
    awaitable-cancellable; a cancelled task leaves nothing running behind it.
    """
    interval = settings.freshness_check_interval_seconds
    logger.info("freshness monitor started (read-only recheck every %ds)", interval)
    try:
        while True:
            await asyncio.sleep(interval)
            try:
                # FRESHNESS.refresh never raises by contract: a database
                # outage is captured as an UNAVAILABLE snapshot
                # (db_reachable=False) and recovery as a fresh verdict, all
                # without restarting the process. The guard below is defence
                # in depth (review M1): one tick that breaks the contract
                # must not disable monitoring for the rest of the process
                # life.
                snapshot = await FRESHNESS.refresh(AsyncSessionLocal)
                logger.debug("freshness monitor: state=%s db_reachable=%s",
                             snapshot.state.value, snapshot.db_reachable)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — a tick cannot kill monitoring
                logger.error("freshness monitor iteration failed (%s: %s) — "
                             "retrying next interval", type(exc).__name__,
                             redact_secrets(str(exc))[:200])
    except asyncio.CancelledError:
        logger.info("freshness monitor stopped")
        raise


def start_freshness_monitor() -> asyncio.Task:
    """Spawn the monitor once; a second call returns the live task."""
    global _freshness_monitor_task
    if (_freshness_monitor_task is not None
            and not _freshness_monitor_task.done()):
        return _freshness_monitor_task
    _freshness_monitor_task = asyncio.get_running_loop().create_task(
        freshness_monitor_loop(), name="freshness-monitor"
    )
    return _freshness_monitor_task


async def stop_freshness_monitor(task: asyncio.Task | None = None) -> None:
    """Cancel and await the monitor so shutdown does not leak the task."""
    global _freshness_monitor_task
    task = task if task is not None else _freshness_monitor_task
    if _freshness_monitor_task is task:
        _freshness_monitor_task = None
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
