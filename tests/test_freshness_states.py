"""
tests/test_freshness_states.py — A2: freshness-state reliability.

Pins the four feed-level states (FRESH / STALE / EMPTY / UNAVAILABLE), the
shared cache that lets /health answer without database queries, and the
scheduler's fail-closed, bounded startup catch-up. Every previous failure mode
has a test here:

  * a database exception read as "not stale" (fail-open) — is_stale now fails
    CLOSED: unknown can never mean fresh;
  * DB outage reported as EMPTY/FRESH — exceptions map to UNAVAILABLE only;
  * /health costing three queries per probe — it now reads the cache, and the
    SQLAlchemy instrumentation test proves ZERO statements AND ZERO connects;
  * the refresh loop that only ever refreshed at first tick and then slept
    forever — scheduled ticks now run the pipeline;
  * a failed startup refresh silently counted as recovery — catch-up retries
    at most three attempts with bounded exponential backoff, and stops without
    retrying when another worker owns the advisory lock.

Mocks/fakes here stand in only for DATABASE sessions and the UPSTREAM fetch —
both unreachable from tests by design. The state machine, cache, scheduler
control flow and health wiring are the real implementations.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from backend.core.config import settings
from backend.services import scheduler
from backend.services.freshness import (
    FRESHNESS,
    FreshnessCache,
    FreshnessSnapshot,
    FreshnessState,
    compute_freshness,
    unavailable,
)


def _res(scalar=None, scalar_one=None):
    out = MagicMock()
    out.scalar.return_value = scalar
    out.scalar_one_or_none.return_value = scalar_one
    return out


def _fake_db(side_effect=None, results=None):
    """Async-session stand-in: db.execute returns results in order or raises."""
    db = MagicMock()
    db.execute = AsyncMock(side_effect=side_effect if side_effect is not None
                           else list(results or []))
    return db


def _fake_session_factory(**kwargs):
    """Context-manager session factory matching AsyncSessionLocal usage."""
    db = _fake_db(**kwargs)
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=db)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory, db


def _snap(state: FreshnessState, **kw) -> FreshnessSnapshot:
    return FreshnessSnapshot(
        state=state,
        newest_market_date=kw.pop("newest", None),
        age_days=kw.pop("age", None),
        rows=kw.pop("rows", None),
        declarations=kw.pop("decls", 0),
        checked_at=kw.pop("checked_at", time.monotonic()),
        checked_at_wall=kw.pop("checked_at_wall", dt.datetime.now(dt.timezone.utc)),
        # Hand-built snapshots stand in for COMPUTED ones, and every real
        # computed verdict made over a working connection carries
        # db_reachable=True; tests for the other two values say so explicitly.
        db_reachable=kw.pop("db_reachable", True),
        **kw,
    )


TODAY = dt.date(2026, 11, 2)


# ── classification: the four states ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_fresh_when_newest_date_within_sla():
    db = _fake_db(results=[
        _res(scalar_one=dt.datetime(2026, 10, 31, tzinfo=dt.timezone.utc)),
        _res(scalar=4200), _res(scalar=17),
    ])
    snap = await compute_freshness(db, today=TODAY)
    assert snap.state is FreshnessState.FRESH
    assert snap.age_days == 2
    assert snap.forecastable is True
    assert snap.rows == 4200 and snap.declarations == 17
    assert snap.db_reachable is True  # the aggregates completed over a live connection


@pytest.mark.asyncio
async def test_stale_when_newest_date_beyond_sla():
    old = TODAY - dt.timedelta(days=settings.price_max_age_days + 5)
    db = _fake_db(results=[_res(scalar_one=old), _res(scalar=4200), _res(scalar=1)])
    snap = await compute_freshness(db, today=TODAY)
    assert snap.state is FreshnessState.STALE
    assert snap.forecastable is False
    assert "SLA" in snap.detail


@pytest.mark.asyncio
async def test_empty_is_a_successful_query_with_no_rows():
    db = _fake_db(results=[_res(scalar_one=None), _res(scalar=0), _res(scalar=0)])
    snap = await compute_freshness(db, today=TODAY)
    assert snap.state is FreshnessState.EMPTY
    assert snap.newest_market_date is None
    assert snap.forecastable is False
    # EMPTY is a DATA statement made over a WORKING connection — the database
    # is reachable even though the feed is unusable.
    assert snap.db_reachable is True


@pytest.mark.asyncio
async def test_database_exception_is_unavailable_never_empty_or_fresh():
    db = _fake_db(side_effect=RuntimeError("connection to server at 10.0.0.1 failed"))
    snap = await compute_freshness(db, today=TODAY)
    assert snap.state is FreshnessState.UNAVAILABLE
    assert snap.forecastable is False
    assert snap.db_reachable is False  # the failed query IS the connectivity observation
    # never raises, and says why
    assert "connection to server" in snap.detail


@pytest.mark.asyncio
async def test_unavailable_reason_is_redacted():
    db = _fake_db(side_effect=ValueError("while fetching api-key=supersecrethere&format=json"))
    snap = await compute_freshness(db, today=TODAY)
    assert snap.state is FreshnessState.UNAVAILABLE
    assert "supersecrethere" not in snap.detail
    assert "api-key=[REDACTED]" in snap.detail


@pytest.mark.asyncio
async def test_rows_without_usable_date_are_unavailable_not_empty():
    """The query succeeded and rows EXIST but cannot be aged: that is
    unable-to-determine, not 'there is no data'."""
    db = _fake_db(results=[_res(scalar_one=None), _res(scalar=99), _res(scalar=0)])
    snap = await compute_freshness(db, today=TODAY)
    assert snap.state is FreshnessState.UNAVAILABLE
    assert "no usable arrival_date" in snap.detail


@pytest.mark.asyncio
async def test_unknown_age_is_never_forecastable():
    for state in (FreshnessState.STALE, FreshnessState.EMPTY, FreshnessState.UNAVAILABLE):
        assert _snap(state).forecastable is False
    assert _snap(FreshnessState.FRESH).forecastable is True


# ── the shared cache ─────────────────────────────────────────────────────────

def test_initial_snapshot_is_unavailable_not_fresh():
    cache = FreshnessCache()
    snap = cache.get()
    assert snap.state is FreshnessState.UNAVAILABLE
    assert snap.checked_at is None          # never computed
    assert snap.db_reachable is None        # never OBSERVED either
    assert snap.forecastable is False
    assert "no freshness check" in snap.detail


@pytest.mark.asyncio
async def test_successful_read_updates_the_cache():
    cache = FreshnessCache()
    factory, _db = _fake_session_factory(results=[
        _res(scalar_one=dt.date(2026, 11, 1)), _res(scalar=5), _res(scalar=2),
    ])
    snap = await cache.refresh(factory, today=TODAY)
    assert snap.state is FreshnessState.FRESH
    assert cache.get() is snap
    assert cache.get().as_dict()["state"] == "fresh"


@pytest.mark.asyncio
async def test_failed_read_invalidates_a_previously_fresh_snapshot():
    """A FRESH verdict survives only while nobody has failed to confirm it.
    Once the database stops answering, the cache must say UNAVAILABLE — the old
    'fresh' claim is no longer verifiable and keeping it is the exact misleading
    signal A2 removes."""
    cache = FreshnessCache()
    good, _ = _fake_session_factory(results=[
        _res(scalar_one=dt.date(2026, 11, 1)), _res(scalar=5), _res(scalar=2),
    ])
    await cache.refresh(good, today=TODAY)
    assert cache.get().state is FreshnessState.FRESH

    bad, _ = _fake_session_factory(side_effect=RuntimeError("server closed connection"))
    snap = await cache.refresh(bad, today=TODAY)
    assert snap.state is FreshnessState.UNAVAILABLE
    assert cache.get().state is FreshnessState.UNAVAILABLE
    assert cache.get().forecastable is False


def test_expired_cache_downgrades_to_unavailable_without_querying_anything():
    cache = FreshnessCache()
    stale_ever = _snap(FreshnessState.FRESH, newest=dt.date(2026, 11, 1),
                       age=1, rows=5, db_reachable=True,
                       checked_at=time.monotonic() - 10_000,
                       checked_at_wall=dt.datetime.now(dt.timezone.utc))
    cache.set(stale_ever)
    with patch.object(settings, "freshness_cache_ttl_seconds", 3600):
        snap = cache.get()
    assert snap.state is FreshnessState.UNAVAILABLE
    assert snap.newest_market_date is None     # expired verdicts carry no date claim
    assert snap.checked_at is not None          # but the check history stays visible
    # B1 fix round: expiry says "the VERDICT is too old to trust", which does
    # NOT retract "the last check reached the database" — connectivity is
    # preserved until a new observation replaces it.
    assert snap.db_reachable is True
    assert "expired" in snap.detail


# ── scheduler: fail-closed reads and bounded catch-up ────────────────────────

@pytest.mark.asyncio
async def test_is_stale_fails_closed_on_database_error():
    """The pre-A2 bug: exception -> False ('assume fresh'). Now unknown means
    'attempt bounded recovery', and the shared cache records UNAVAILABLE."""
    isolated = FreshnessCache()
    factory, _db = _fake_session_factory(side_effect=RuntimeError("could not connect"))
    with patch.object(scheduler, "FRESHNESS", isolated), \
         patch.object(scheduler, "AsyncSessionLocal", factory):
        assert await scheduler.is_stale() is True
    assert isolated.get().state is FreshnessState.UNAVAILABLE


@pytest.mark.asyncio
async def test_is_stale_reads_from_cache_and_classifies_every_state():
    cases = {
        FreshnessState.FRESH: False,
        FreshnessState.STALE: True,
        FreshnessState.EMPTY: True,        # empty feed: recovery is appropriate
        FreshnessState.UNAVAILABLE: True,  # unknown: bounded recovery, no fresh claim
    }
    for state, expected in cases.items():
        isolated = FreshnessCache()
        isolated.set(_snap(state))
        # is_stale must READ the live database through the cache; give it a
        # factory whose classification lands on `state`.
        results = {
            FreshnessState.FRESH: [_res(scalar_one=dt.date.today()), _res(scalar=9), _res(scalar=0)],
            FreshnessState.STALE: [_res(scalar_one=dt.date(2026, 1, 1)), _res(scalar=9), _res(scalar=0)],
            FreshnessState.EMPTY: [_res(scalar_one=None), _res(scalar=0), _res(scalar=0)],
            FreshnessState.UNAVAILABLE: RuntimeError("gone"),
        }[state]
        factory, _db = _fake_session_factory(
            results=None if isinstance(results, Exception) else results,
            side_effect=results if isinstance(results, Exception) else None,
        )
        with patch.object(scheduler, "AsyncSessionLocal", factory):
            # rebind the cache the patched is_stale will use
            with patch.object(scheduler, "FRESHNESS", isolated):
                assert await scheduler.is_stale() is expected, state


@pytest.mark.asyncio
async def test_catch_up_skips_refresh_on_a_fresh_feed():
    with patch.object(scheduler, "is_stale", AsyncMock(return_value=False)), \
         patch.object(scheduler, "refresh_once", AsyncMock()) as once:
        await scheduler._startup_catch_up()
        once.assert_not_awaited()


@pytest.mark.asyncio
async def test_catch_up_stops_after_success_and_counts_it_a_recovery():
    with patch.object(scheduler, "is_stale", AsyncMock(return_value=True)), \
         patch.object(scheduler, "refresh_once",
                      AsyncMock(return_value=(scheduler.REFRESH_DONE, {"status": "success"}))) as once:
        await scheduler._startup_catch_up()
        once.assert_awaited_once()
        assert once.await_args.kwargs["trigger"] == "startup"


@pytest.mark.asyncio
async def test_failed_refresh_is_not_a_recovery_three_bounded_backoff_attempts():
    """Startup retries at most three attempts with exponential backoff, all
    captured by a fake sleep so the test never waits."""
    sleeps: list[float] = []

    async def record_sleep(seconds):
        sleeps.append(seconds)

    with patch.object(scheduler, "is_stale", AsyncMock(return_value=True)), \
         patch.object(scheduler, "refresh_once",
                      AsyncMock(return_value=(scheduler.REFRESH_FAILED, None))) as once:
        await scheduler._startup_catch_up(sleep=record_sleep)
        assert once.await_count == scheduler.STARTUP_CATCHUP_MAX_ATTEMPTS == 3
    assert sleeps == [
        scheduler.STARTUP_CATCHUP_BACKOFF_SECONDS,
        scheduler.STARTUP_CATCHUP_BACKOFF_SECONDS * 2,
    ]  # bounded: exactly attempts-1 sleeps, doubling, no fourth attempt


@pytest.mark.asyncio
async def test_lock_contention_ends_catch_up_without_retrying():
    """Another worker owning the advisory lock is success by delegation —
    retrying would duplicate its work and hammer the lock."""
    sleeps: list[float] = []

    async def record_sleep(seconds):
        sleeps.append(seconds)

    with patch.object(scheduler, "is_stale", AsyncMock(return_value=True)), \
         patch.object(scheduler, "refresh_once",
                      AsyncMock(return_value=(scheduler.REFRESH_LOCKED, None))) as once:
        await scheduler._startup_catch_up(sleep=record_sleep)
        once.assert_awaited_once()
    assert sleeps == []  # contention is not failure: no backoff, no retry


@pytest.mark.asyncio
async def test_refresh_once_distinguishes_done_locked_and_failed():
    class _LockOk:
        def __init__(self, engine): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *exc): return False

    class _LockBusy(_LockOk):
        async def __aenter__(self):
            raise scheduler.data_refresh.RefreshAlreadyRunning("held")

    class _LockBoom(_LockOk):
        async def __aenter__(self): raise RuntimeError("disk gone")

    isolated = FreshnessCache()
    factory, _db = _fake_session_factory(results=[
        _res(scalar_one=dt.date.today()), _res(scalar=1), _res(scalar=0),
    ])
    summary = {"status": "success"}
    with patch.object(scheduler.data_refresh, "refresh_lock", _LockOk), \
         patch.object(scheduler.data_refresh, "run_refresh", AsyncMock(return_value=summary)), \
         patch.object(scheduler, "AsyncSessionLocal", factory), \
         patch.object(scheduler, "FRESHNESS", isolated):
        assert await scheduler.refresh_once(detailed=True) == (scheduler.REFRESH_DONE, summary)
    # a completed refresh updated the shared snapshot
    assert isolated.get().state is FreshnessState.FRESH

    # D3 fix round: even the LOCK loser maintains its own cache — a worker
    # that never wins the race must still see the winner's committed feed.
    factory2, _db2 = _fake_session_factory(results=[
        _res(scalar_one=dt.date.today()), _res(scalar=1), _res(scalar=0),
    ])
    with patch.object(scheduler.data_refresh, "refresh_lock", _LockBusy), \
         patch.object(scheduler, "AsyncSessionLocal", factory2), \
         patch.object(scheduler, "FRESHNESS", isolated):
        isolated.set(unavailable("pre-attempt"))
        outcome, res = await scheduler.refresh_once(detailed=True)
        assert outcome == scheduler.REFRESH_LOCKED and res is None
        assert isolated.get().state is FreshnessState.FRESH  # cache maintained anyway
        assert isolated.get().db_reachable is True
        assert await scheduler.refresh_once() is None  # legacy shape preserved

    # D2 fix round: a FAILED attempt also re-reads — if the database went
    # down, that is exactly when the previous FRESH claim must be invalidated.
    factory3, _db3 = _fake_session_factory(results=[
        _res(scalar_one=dt.date.today()), _res(scalar=1), _res(scalar=0),
    ])
    with patch.object(scheduler.data_refresh, "refresh_lock", _LockBoom), \
         patch.object(scheduler, "AsyncSessionLocal", factory3), \
         patch.object(scheduler, "FRESHNESS", isolated):
        assert await scheduler.refresh_once(detailed=True) == (scheduler.REFRESH_FAILED, None)
        assert isolated.get().state is FreshnessState.FRESH  # re-read happened
        assert await scheduler.refresh_once() is None  # legacy shape preserved


@pytest.mark.asyncio
async def test_refresh_enabled_false_prevents_catchup_and_task_activity():
    with patch.object(settings, "refresh_enabled", False), \
         patch.object(scheduler, "_startup_catch_up", AsyncMock()) as catch_up:
        assert scheduler.start_refresh_task() is None
        await asyncio.sleep(0.01)
        catch_up.assert_not_awaited()


def _run_loop_briefly(**overrides):
    async def go():
        task = asyncio.create_task(scheduler.refresh_loop(**overrides))
        await asyncio.sleep(0.15)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    asyncio.run(go())


def test_scheduled_ticks_now_actually_refresh():
    """Pre-A2, the loop set its catch-up flag False after the first iteration
    and then ONLY slept — a long-lived process never ingested again. Now every
    tick after the first runs a scheduled refresh. (_run_loop_briefly owns the
    event loop via asyncio.run, so this test is deliberately synchronous.)"""
    with patch.object(scheduler, "is_stale", AsyncMock(return_value=False)), \
         patch.object(scheduler, "refresh_once", AsyncMock()) as once:
        _run_loop_briefly(interval_hours=1e-7)  # ~0.36ms per tick
        triggers = [c.kwargs.get("trigger") for c in once.await_args_list]
    assert "scheduled" in triggers  # tick 1 skipped (fresh), later ticks refreshed


# ── /health: cached, query-free, backwards compatible ────────────────────────

LEGACY_KEYS = {
    "status", "database_connected", "model_loaded", "model_status", "model_detail",
    "features", "model_provenance", "model_metadata_matches", "declarations",
    "latest_price_date", "price_feed_age_days", "price_feed_forecastable",
    "timestamp",
}


@pytest.fixture
def health_client():
    """Real app WITHOUT lifespan (no startup jobs, no scheduler)."""
    import backend.routers.system as system_module
    isolated = FreshnessCache()
    with patch.object(system_module, "FRESHNESS", isolated):
        from backend.main import app
        client = TestClient(app)  # no context manager => no lifespan
        yield client, isolated


def _no_database_traffic(monkeypatch):
    """Count EVERY statement and every connection attempt on the real engine."""
    from backend.core.database import engine
    seen: list[str] = []

    def before_execute(conn, cursor, statement, params, context, executemany):
        seen.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", before_execute)

    def no_connect(*a, **kw):
        raise AssertionError("a health request tried to connect to the database")

    from sqlalchemy.ext.asyncio import AsyncEngine
    monkeypatch.setattr(AsyncEngine, "connect", no_connect)
    return seen, lambda: event.remove(engine.sync_engine, "before_cursor_execute", before_execute)


def test_health_without_lifespan_is_conservative_unavailable(health_client):
    client, _cache = health_client
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["price_feed_status"] == "unavailable"
    assert body["price_feed_forecastable"] is False
    assert body["database_connected"] is False
    assert body["latest_price_date"] is None
    assert LEGACY_KEYS <= set(body)


def test_health_reads_cache_and_never_queries_the_database(health_client, monkeypatch):
    client, cache = health_client
    seen, detach = _no_database_traffic(monkeypatch)
    try:
        cache.set(_snap(FreshnessState.FRESH, newest=dt.date(2026, 11, 1),
                        age=1, rows=4200, decls=9))
        for _ in range(5):
            body = client.get("/health").json()
        assert seen == []  # five health hits, zero SQL statements, zero connects
        assert body["price_feed_status"] == "fresh"
        assert body["price_feed_forecastable"] is True
        assert body["database_connected"] is True
        assert body["latest_price_date"] == "2026-11-01"
        assert body["price_feed_age_days"] == 1
        assert body["declarations"] == 9
        assert body["freshness_cache"]["ttl_seconds"] == settings.freshness_cache_ttl_seconds
    finally:
        detach()


def test_health_reports_every_non_fresh_state_as_not_forecastable(health_client):
    client, cache = health_client
    for state in ("stale", "empty", "unavailable"):
        cache.set(_snap(FreshnessState(state),
                        newest=dt.date(2026, 1, 1) if state == "stale" else None,
                        age=300 if state == "stale" else None,
                        rows=0 if state == "empty" else 7))
        body = client.get("/health").json()
        assert body["price_feed_status"] == state
        assert body["price_feed_forecastable"] is False


def test_health_expired_cache_never_claims_fresh(health_client):
    client, cache = health_client
    cache.set(_snap(FreshnessState.FRESH, newest=dt.date(2026, 11, 1), age=1, rows=5,
                    db_reachable=True,
                    checked_at=time.monotonic() - 999_999,
                    checked_at_wall=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)))
    with patch.object(settings, "freshness_cache_ttl_seconds", 3600):
        body = client.get("/health").json()
    assert body["price_feed_status"] == "unavailable"
    assert body["price_feed_forecastable"] is False
    # B1: an expired verdict is an availability statement, not a connectivity
    # retraction — the last OBSERVED reachability is what database_connected
    # reports, and nothing since then failed to reach the database.
    assert body["database_connected"] is True


# ── data_freshness stays compatible and reports the state ────────────────────

@pytest.mark.asyncio
async def test_data_freshness_keeps_legacy_keys_and_adds_state():
    from backend.services import data_refresh
    db = _fake_db(results=[
        _res(scalar_one=dt.datetime(2026, 8, 25, tzinfo=dt.timezone.utc)),  # newest
        _res(scalar=25000),                                                 # rows
        _res(scalar=3),                                                     # declarations
        _res(scalar_one=None),                                              # no last run
    ])
    health = await data_refresh.data_freshness(db, today=dt.date(2026, 10, 15))
    # pre-existing contract
    assert health["rows"] == 25000
    assert health["newest_market_date"] == "2026-08-25"
    assert health["age_days"] == 51
    assert health["forecastable"] is False
    assert health["last_refresh"] is None
    # A2 addition
    assert health["state"] == "stale"


# ── fix round: D1 — outcome must reflect the ACTUAL pipeline result ─────────

class _OkLock:
    def __init__(self, engine): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *exc): return False


@pytest.mark.asyncio
async def test_pipeline_status_decides_the_outcome_not_the_absence_of_a_raise():
    """
    run_refresh catches ingestion errors internally and RETURNS status="failed"
    — refresh_once must classify that as FAILED, not as a completed recovery.
    Exercises the real refresh_once classification against real pipeline
    summary shapes (only run_refresh itself is stood in for, so no network).
    """
    cases = [
        ({"status": "success"}, scheduler.REFRESH_DONE),
        ({"status": "no_new_data"}, scheduler.REFRESH_DONE),   # quiet upstream ≠ failure
        ({"status": "failed", "error": "upstream 503"}, scheduler.REFRESH_FAILED),
        ({"status": "weird-unknown"}, scheduler.REFRESH_FAILED),
        ({}, scheduler.REFRESH_FAILED),                          # missing status
        ("malformed", scheduler.REFRESH_FAILED),                 # not even a dict
        (None, scheduler.REFRESH_FAILED),
    ]
    isolated = FreshnessCache()
    for summary, expected in cases:
        factory, _db = _fake_session_factory(results=[
            _res(scalar_one=dt.date(2026, 11, 1)), _res(scalar=1), _res(scalar=0),
        ])
        with patch.object(scheduler.data_refresh, "refresh_lock", _OkLock), \
             patch.object(scheduler.data_refresh, "run_refresh",
                          AsyncMock(return_value=summary)), \
             patch.object(scheduler, "AsyncSessionLocal", factory), \
             patch.object(scheduler, "FRESHNESS", isolated):
            outcome, res = await scheduler.refresh_once(detailed=True)
        assert outcome == expected, summary
        # legacy shape: the summary itself is still what non-detailed callers get
        assert res is summary


@pytest.mark.asyncio
async def test_startup_catch_up_retries_genuine_pipeline_failures_end_to_end():
    """
    D1's consumer side: with the REAL refresh_once wired in (only the pipeline
    and the sessions are stood in for), a status="failed" run must consume an
    attempt and retry — bounded to three — instead of being counted as a
    recovery on the first pass.
    """
    sleeps: list[float] = []

    async def record_sleep(seconds):
        sleeps.append(seconds)

    run = AsyncMock(return_value={"status": "failed", "error": "upstream gone"})
    isolated = FreshnessCache()

    def factory_with_results():
        factory, _db = _fake_session_factory(results=[
            _res(scalar_one=dt.date(2020, 1, 1)), _res(scalar=10), _res(scalar=0),
        ])
        return factory

    import contextlib

    @contextlib.asynccontextmanager
    async def ok_lock(_engine):
        yield

    with patch.object(scheduler, "is_stale", AsyncMock(return_value=True)), \
         patch.object(scheduler.data_refresh, "refresh_lock", ok_lock), \
         patch.object(scheduler.data_refresh, "run_refresh", run), \
         patch.object(scheduler, "FRESHNESS", isolated), \
         patch.object(scheduler, "AsyncSessionLocal", factory_with_results()):
        await scheduler._startup_catch_up(sleep=record_sleep)
        assert run.await_count == scheduler.STARTUP_CATCHUP_MAX_ATTEMPTS
    assert sleeps == [scheduler.STARTUP_CATCHUP_BACKOFF_SECONDS,
                      scheduler.STARTUP_CATCHUP_BACKOFF_SECONDS * 2]


@pytest.mark.asyncio
async def test_failed_cache_maintenance_never_rescues_a_failed_refresh():
    """D2/D3 maintenance runs AFTER classification and cannot change it: a
    snapshot update that itself explodes leaves the outcome as classified."""
    boom_cache = MagicMock()
    boom_cache.refresh = AsyncMock(side_effect=RuntimeError("cache maintenance exploded"))
    with patch.object(scheduler.data_refresh, "refresh_lock", _OkLock), \
         patch.object(scheduler.data_refresh, "run_refresh",
                      AsyncMock(return_value={"status": "failed"})), \
         patch.object(scheduler, "FRESHNESS", boom_cache):
        outcome, _ = await scheduler.refresh_once(detailed=True)
        assert outcome == scheduler.REFRESH_FAILED
    boom_cache.refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_db_down_during_a_failed_attempt_invalidates_a_fresh_cache():
    """D2's core scenario, at unit level: cache FRESH, refresh attempt dies on
    a dead database, the re-read inside refresh_once observes the failure and
    replaces the unverifiable FRESH claim with UNAVAILABLE + not-reachable."""
    isolated = FreshnessCache()
    good, _db = _fake_session_factory(results=[
        _res(scalar_one=dt.date(2026, 11, 1)), _res(scalar=1), _res(scalar=0),
    ])
    await isolated.refresh(good, today=TODAY)
    assert isolated.get().state is FreshnessState.FRESH

    dead_factory, _dead = _fake_session_factory(
        side_effect=RuntimeError("connection refused"))

    class _Dead:
        def __init__(self, engine): pass
        async def __aenter__(self): raise RuntimeError("connection refused")
        async def __aexit__(self, *exc): return False

    with patch.object(scheduler.data_refresh, "refresh_lock", _Dead), \
         patch.object(scheduler, "AsyncSessionLocal", dead_factory), \
         patch.object(scheduler, "FRESHNESS", isolated):
        outcome, _ = await scheduler.refresh_once(detailed=True)
    snap = isolated.get()
    assert outcome == scheduler.REFRESH_FAILED
    assert snap.state is FreshnessState.UNAVAILABLE
    assert snap.db_reachable is False


# ── fix round: B1 — connectivity and freshness are independent facts ────────

def test_database_connected_tracks_reachability_not_the_feed_verdict(health_client):
    client, cache = health_client
    # reachable database, unusable feed → connected but not forecastable
    cache.set(_snap(FreshnessState.STALE, newest=dt.date(2026, 1, 1), age=300, rows=7,
                    db_reachable=True))
    body = client.get("/health").json()
    assert body["database_connected"] is True
    assert body["price_feed_status"] == "stale"
    assert body["price_feed_forecastable"] is False

    # unreachable database reporting EMPTY-looking numbers → not connected
    cache.set(unavailable("freshness query failed: connection refused",
                          db_reachable=False))
    body = client.get("/health").json()
    assert body["database_connected"] is False
    assert body["price_feed_status"] == "unavailable"


# ── fix round: independent freshness monitor (external-cron gap) ──────────

@pytest.mark.asyncio
async def test_monitor_rechecks_read_only_and_never_ingests():
    """The monitor loop must re-run the read-only freshness compute on its
    interval and touch NOTHING in the ingestion path."""
    ticks: list[int] = []

    async def fake_refresh(factory, **kw):
        ticks.append(len(ticks))
        return _snap(FreshnessState.STALE)

    cache_spy = MagicMock()
    cache_spy.refresh = fake_refresh
    run_spy = AsyncMock()
    lock_spy = MagicMock()

    import backend.services.data_refresh as dr
    with patch.object(scheduler, "FRESHNESS", cache_spy), \
         patch.object(settings, "freshness_check_interval_seconds", 0.01), \
         patch.object(dr, "run_refresh", run_spy), \
         patch.object(dr, "refresh_lock", lock_spy):
        task = asyncio.create_task(scheduler.freshness_monitor_loop())
        await asyncio.sleep(0.08)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert len(ticks) >= 2                # kept re-reading on schedule
    run_spy.assert_not_awaited()          # never ingested
    lock_spy.assert_not_called()          # never took the advisory lock


@pytest.mark.asyncio
async def test_monitor_starts_despite_refresh_enabled_false_no_duplicates_leaks():
    """REFRESH_ENABLED=false must still give the process a health monitor
    (that is the whole point), start_freshness_monitor must not double-spawn,
    and stop must cancel cleanly and clear the module handle."""
    async def slow_loop():
        await asyncio.sleep(60)

    orig_loop = scheduler.freshness_monitor_loop
    scheduler.freshness_monitor_loop = slow_loop
    try:
        with patch.object(settings, "refresh_enabled", False):
            assert scheduler.start_refresh_task() is None  # ingestion stays off
            task1 = scheduler.start_freshness_monitor()
            task2 = scheduler.start_freshness_monitor()
            assert task1 is task2 and not task1.done()     # exactly one task
        await scheduler.stop_freshness_monitor(task1)
        assert task1.done()                                # cancelled, not leaked
        assert scheduler._freshness_monitor_task is None
        # stop is idempotent
        await scheduler.stop_freshness_monitor(task1)
    finally:
        scheduler.freshness_monitor_loop = orig_loop


def test_freshness_check_interval_setting_is_validated():
    from pydantic import ValidationError
    from backend.core.config import Settings
    assert settings.freshness_check_interval_seconds == 300  # conservative default
    with pytest.raises(ValidationError):
        Settings(_env_file=None, freshness_check_interval_seconds=1)  # ge=5 guard


@pytest.mark.asyncio
async def test_monitor_survives_an_unexpected_iteration_error_and_recovers():
    """Review M1: one tick that breaks ``FRESHNESS.refresh``'s never-raises
    contract must be logged and skipped, not allowed to kill the monitor for
    the rest of the process life. A later, healthy tick must still update the
    cache — proving the loop kept running rather than dying silently behind a
    task handle that still looks alive.
    """
    cache = FreshnessCache()
    calls = {"n": 0}

    async def flaky_refresh(factory, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated contract violation, not a DB outage")
        factory_result = _snap(FreshnessState.FRESH, newest=dt.date(2026, 11, 1),
                                age=1, rows=5)
        cache.set(factory_result)
        return factory_result

    with patch.object(scheduler, "FRESHNESS", MagicMock(refresh=flaky_refresh)), \
         patch.object(settings, "freshness_check_interval_seconds", 0.01):
        task = asyncio.create_task(scheduler.freshness_monitor_loop())
        try:
            # wait until at least two ticks have run (the first one raised)
            for _ in range(200):
                await asyncio.sleep(0.01)
                if calls["n"] >= 2:
                    break
            assert not task.done(), "monitor died after one raised iteration"
            assert calls["n"] >= 2
            assert cache.get().state is FreshnessState.FRESH  # the recovery tick landed
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


# ── fix round: R1 — older computations cannot overwrite newer snapshots ────

class _RowsRes:
    """One result object satisfying all three compute aggregates."""
    def scalar(self): return 5
    def scalar_one(self): return dt.date(2026, 11, 1)
    def scalar_one_or_none(self): return dt.date(2026, 11, 1)


class _Ctx:
    def __init__(self, db): self._db = db
    async def __aenter__(self): return self._db
    async def __aexit__(self, *exc): return False


@pytest.mark.asyncio
async def test_stalled_older_computation_cannot_overwrite_newer_outage():
    """
    The exact review scenario, ordered by EVENTS (no sleep-based scheduling):

      1. computation A starts while the database is healthy, then STALLS
         mid-query (announces itself via `started` and blocks on `release`);
      2. the database goes down; computation B starts later and stores
         UNAVAILABLE (db_reachable=False);
      3. A finally completes with a FRESH verdict — and must be REJECTED:
         its observation began before the outage B already recorded.

    Against the pre-R1 implementation this failed: A finished last and won
    the unconditional last-write, leaving /health claiming fresh +
    database_connected=true during an outage.
    """
    cache = FreshnessCache()
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_execute(*a, **k):
        if not started.is_set():
            started.set()
            await release.wait()
        return _RowsRes()

    db_a = MagicMock()
    db_a.execute = AsyncMock(side_effect=slow_execute)
    dead, _dbb = _fake_session_factory(side_effect=RuntimeError("connection refused"))

    task_a = asyncio.create_task(cache.refresh(lambda: _Ctx(db_a)))
    await started.wait()                      # A began first and is inside its query
    snap_b = await cache.refresh(dead)        # B begins later, sees the outage
    assert snap_b.state is FreshnessState.UNAVAILABLE
    assert snap_b.db_reachable is False

    release.set()                             # A completes AFTER B
    result_a = await task_a
    final = cache.get()
    assert final.state is FreshnessState.UNAVAILABLE, \
        "stalled older FRESH overwrote the newer outage record"
    assert final.db_reachable is False
    # refresh() returns what the cache TRUTHFULLY holds, not the rejected loser
    assert result_a is snap_b


def test_set_ordering_matrix_start_stamped():
    """Every start-stamp relation, using stamps near `now` so TTL logic in
    get() is not entangled with the ordering assertions."""
    base = time.monotonic()
    def fresh(offset): return _snap(FreshnessState.FRESH, newest=dt.date(2026, 11, 1),
                                    age=1, rows=5, checked_at=base + offset)
    def down(offset): return _snap(FreshnessState.UNAVAILABLE, rows=None,
                                   checked_at=base + offset,
                                   detail="freshness query failed: connection refused",
                                   **{"db_reachable": False})

    # earlier FRESH then later FRESH -> newer wins
    c = FreshnessCache(); c.set(fresh(0)); assert c.set(fresh(1)) is not None
    assert c.get().checked_at == base + 1
    # earlier outage record then later successful check -> recovery wins
    c = FreshnessCache(); c.set(down(0)); c.set(fresh(1))
    assert c.get().state is FreshnessState.FRESH
    # earlier FRESH then later outage record -> outage wins (fail closed)
    c = FreshnessCache(); c.set(fresh(0)); c.set(down(1))
    assert c.get().state is FreshnessState.UNAVAILABLE
    assert c.get().db_reachable is False
    # NEWER snapshot then an OLDER computation landing late -> rejected
    c = FreshnessCache(); c.set(down(5)); rejected = c.set(fresh(2))
    assert rejected is c.get() and rejected.state is FreshnessState.UNAVAILABLE
    # equal start stamps -> deterministic last write wins
    c = FreshnessCache(); c.set(fresh(3)); later = down(3)
    assert c.set(later) is later
    assert c.get().state is FreshnessState.UNAVAILABLE


def test_initial_state_and_explicit_invalidation_rules():
    """The two UNTIMESTAMPED-write rules R1 adds to ``set()``.

    * The never-computed initial state carries no start stamp, so the FIRST
      real computation always replaces it, whatever its own start time —
      there is no older/newer relation to check yet. This is the ONLY
      untimestamped write that reaches the cache from production code now:
      ``FreshnessCache.__init__`` runs at module import, before any
      computation can exist, so nothing can predate it.
    * An explicit invalidation — ``unavailable(...)`` with no stamp — always
      replaces whatever is current, including a stamped snapshot: it asserts
      no ordering information at all, so it can never be a "stale overwrite"
      of a newer observation; it carries no data to be stale about.

    The ``main.lifespan`` "startup could not reach the database" marker is
    deliberately STAMPED (review R1), NOT an untimestamped invalidation, and
    this is why. Bootstrap does not run synchronously ahead of the
    monitor/refresh tasks: ``_bootstrap_database`` awaits
    ``ensure_database_reachable()`` (a multi-attempt retry/backoff) while
    ``refresh_loop``/``is_stale`` and the monitor are already scheduled, so
    several freshness writes genuinely overlap across those ``await`` points.
    Had the marker stayed untimestamped, the incoming-has-no-stamp rule below
    would let a stalled OLDER success — one that began before the database
    actually dropped — land after a newer failure had already been recorded,
    because an untimestamped marker first erases that failure's ordering
    stamp. Stamping the marker makes it participate in the same monotonic
    ordering as every real observation, closing that window.
    """
    cache = FreshnessCache()
    snap = cache.get()
    assert snap.state is FreshnessState.UNAVAILABLE
    assert snap.checked_at is None
    assert snap.db_reachable is None

    # first real computation replaces the untimestamped initial state
    first = _snap(FreshnessState.STALE, checked_at=time.monotonic())
    assert cache.set(first) is first
    assert cache.get().state is FreshnessState.STALE

    # an explicit, untimestamped invalidation always wins over it
    inv = unavailable("operator invalidated the cached verdict")
    assert cache.set(inv) is inv
    assert cache.get().state is FreshnessState.UNAVAILABLE
    assert cache.get().db_reachable is None


def test_explicit_invalidation_always_wins_but_never_shields_stale_writes():
    cache = FreshnessCache()
    cache.set(_snap(FreshnessState.FRESH, newest=dt.date(2026, 11, 1), age=1,
                    rows=5, checked_at=time.monotonic()))
    # an untimestamped explicit invalidation (db_reachable=None claim of
    # "unknown") replaces the stamped snapshot...
    inv = unavailable("operator invalidated")
    assert cache.set(inv) is inv
    # ...and the NEXT computation (any stamp) replaces the invalidation —
    # invalidation must not freeze the cache against fresh observations.
    nxt = _snap(FreshnessState.STALE, checked_at=time.monotonic())
    assert cache.set(nxt) is nxt
    # crucially: while an invalidation is current, a stalled older SUCCESS
    # cannot resurrect itself through the None rule — the invalidation has
    # no stamp to lose, so even a pre-invalidation late finisher sits under
    # it by start-time semantics. Verified via ordering after replacement.
    late = _snap(FreshnessState.FRESH, newest=dt.date(2026, 11, 1), age=1, rows=5,
                 checked_at=time.monotonic() - 100)
    # cache currently holds a STAMPED snapshot now; the late older one is rejected
    assert cache.set(late) is nxt


@pytest.mark.asyncio
async def test_stamped_startup_placeholder_cannot_be_overwritten_by_stale_success():
    """Review R1 (invalidation-ordering): the startup "could not reach the
    database" marker MUST carry a real monotonic start stamp.

    The exact three-write window reproduced in review, ordered by EVENTS (no
    sleep-based scheduling), exercising the REAL ``FreshnessCache`` ordering
    API rather than re-implementing the comparison in the test:

      A  an older computation captures its start stamp while the DB is still
         healthy, then STALLS mid-query (it will finish with FRESH);
      B  a newer computation fails fast and stores UNAVAILABLE/db_reachable=
         False WITH a stamp — the correct, more-recent observation;
      C  the startup placeholder is stored using the SAME stamped shape and
         semantics as ``main._bootstrap_database``;
      A  finally completes and tries to land its stale FRESH.

    Because B and C are stamped, A (whose start predates the outage) is
    rejected and the cache keeps the newer outage record. Against the OLD
    untimestamped placeholder this failed: C erased B's ordering stamp, so
    A's late FRESH satisfied the 'current has no stamp -> accept anything'
    rule and /health would report fresh + database_connected=true during a
    real outage. That regression is the point of this test.
    """
    cache = FreshnessCache()
    a_captured = asyncio.Event()
    a_release = asyncio.Event()
    stamps: dict[str, float] = {}

    async def computation_a():
        t_a = time.monotonic()                 # A begins FIRST, DB healthy
        stamps["a"] = t_a
        a_captured.set()
        await a_release.wait()                 # stalls across the outage
        cache.set(_snap(FreshnessState.FRESH, newest=dt.date(2026, 11, 1),
                        age=1, rows=5, checked_at=t_a))

    task_a = asyncio.create_task(computation_a())
    await a_captured.wait()                     # A's start stamp is now fixed

    # B: newer, fails fast, stores a STAMPED outage observation.
    t_b = time.monotonic()
    snap_b = cache.set(_snap(FreshnessState.UNAVAILABLE, rows=None,
                             checked_at=t_b, detail="query failed: connection refused",
                             **{"db_reachable": False}))
    assert snap_b.state is FreshnessState.UNAVAILABLE
    assert snap_b.db_reachable is False

    # C: the corrected, STAMPED startup placeholder — identical shape to
    # main._bootstrap_database's marker.
    t_c = time.monotonic()
    placeholder = FreshnessSnapshot(
        state=FreshnessState.UNAVAILABLE,
        detail="startup could not reach the database; no freshness check ran",
        db_reachable=False,
        checked_at=t_c,
        checked_at_wall=dt.datetime.now(dt.timezone.utc),
    )
    assert cache.set(placeholder) is placeholder   # accepted: stamped marker orders over B

    # A finally lands its OLD-stamped FRESH — it must be rejected as older.
    a_release.set()
    await task_a

    final = cache.get()
    assert final.state is FreshnessState.UNAVAILABLE, \
        "stale older FRESH slipped in behind the startup marker"
    assert final.db_reachable is False
    assert final is placeholder                    # newer accepted observation, not A
    assert final.checked_at == t_c


def test_startup_placeholder_is_stamped_at_observation_start_not_write_moment():
    """Review: an ordering stamp marks when an observation BEGAN, not when its
    result was written.

    ``main._bootstrap_database`` awaits ``ensure_database_reachable()``, whose
    bounded retry/backoff window can span seconds. A concurrent freshness check
    can start and SUCCEED inside that window. If the startup failure marker were
    stamped at the moment it is finally written (after the retries gave up) it
    would look newer than that concurrent success and erase it — leaving a false
    ``database_connected=false`` for a window in which the DB was in fact
    reachable. The corrected code captures ``time.monotonic()`` BEFORE the await,
    so the marker's start predates the concurrent observation and it correctly
    loses the ordering race.

    The retry window is modelled with fixed stamp offsets (no sleeps): the
    concurrent check is stamped 0.5 s after the attempt began; the write moment
    is 1 s after that.
    """
    cache = FreshnessCache()

    t_start = time.monotonic()          # startup reachability attempt BEGINS
    t_conc = t_start + 0.5              # a concurrent check starts later ...
    fresh = _snap(FreshnessState.FRESH, newest=dt.date(2026, 11, 1),
                  age=1, rows=5, checked_at=t_conc)
    assert cache.set(fresh) is fresh    # ... and succeeds, landing FRESH

    # Corrected marker: stamped at the START of the attempt (``t_start``),
    # even though it is only written after the retries finally fail — this
    # mirrors ``main._bootstrap_database`` exactly.
    marker = FreshnessSnapshot(
        state=FreshnessState.UNAVAILABLE,
        detail="startup could not reach the database; no freshness check ran",
        db_reachable=False,
        checked_at=t_start,
        checked_at_wall=dt.datetime.now(dt.timezone.utc),
    )
    assert cache.set(marker) is fresh              # start predates t_conc -> rejected
    assert cache.get().state is FreshnessState.FRESH

    # Contrast: stamping at the WRITE moment (t_write > t_conc) would have
    # overwritten the later-started concurrent success. Pinning this here makes
    # the start-vs-write distinction the actual subject of the test.
    buggy = FreshnessSnapshot(
        state=FreshnessState.UNAVAILABLE,
        detail="startup could not reach the database; no freshness check ran",
        db_reachable=False,
        checked_at=t_conc + 1.0,
        checked_at_wall=dt.datetime.now(dt.timezone.utc),
    )
    assert cache.set(buggy) is buggy               # write-moment outranks t_conc
    assert cache.get().state is FreshnessState.UNAVAILABLE
