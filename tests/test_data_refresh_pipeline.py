"""
tests/test_data_refresh_pipeline.py — AGMARKNET refresh pipeline

The freshness SLA in price_service is only defensible if something keeps the
feed current. This covers that pipeline end to end, with the two properties that
matter most proved explicitly:

  * a refresh RESTORES forecasting when (and only when) the data it fetched
    meets the freshness requirement;
  * re-running it cannot double-count a mandi day.

Unit tests need no services. The integration tests use REAL PostgreSQL with an
injected fake fetcher, so the write path is genuinely exercised while no test
depends on, or touches, the live data.gov.in API. Test rows use a synthetic
commodity name and are removed afterwards.
"""
from __future__ import annotations

import asyncio
import datetime

import pytest
from sqlalchemy import delete, func, select, text

from backend.core.config import settings
from backend.core.models import DataRefreshRun, MandiPrice
from backend.services import data_refresh

TEST_CROP = "Kisanmitra Test Crop"
TEST_DISTRICT = "Kolar"
TEST_MARKET = "KisanmitraTestMandi"


# ── Date parsing / normalisation ──────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("25/08/2026", datetime.date(2026, 8, 25)),      # AGMARKNET's own format
    ("2026-08-25", datetime.date(2026, 8, 25)),      # ISO, our CSV exports
    ("2026-08-25T00:00:00+05:30", datetime.date(2026, 8, 25)),
    (datetime.datetime(2026, 8, 25, 14, 30), datetime.date(2026, 8, 25)),
    (datetime.date(2026, 8, 25), datetime.date(2026, 8, 25)),
])
def test_arrival_date_formats_accepted(raw, expected):
    assert data_refresh.parse_arrival_date(raw) == expected


@pytest.mark.parametrize("bad", [None, "", "not a date", "32/13/2026"])
def test_unparseable_arrival_date_returns_none(bad):
    assert data_refresh.parse_arrival_date(bad) is None


def test_normalize_record_maps_dmi_fields_onto_our_columns():
    rec = data_refresh.normalize_record({
        "State": "Karnataka",
        "District": "Kolar",
        "Market": "Kolar",
        "Commodity": "Ragi (Finger Millet)",
        "Variety": "Local",
        "Arrival_Date": "15/10/2026",
        "Min_Price": "2400",
        "Max_Price": "2800",
        "Modal_Price": "2600",
    })
    # The API's long commodity label must land as the name the bot speaks.
    assert rec["commodity"] == "Ragi"
    assert rec["arrival_date"] == datetime.date(2026, 10, 15)
    assert (rec["min_price"], rec["modal_price"], rec["max_price"]) == (2400.0, 2600.0, 2800.0)


def test_normalize_record_without_price_is_not_silently_zeroed():
    rec = data_refresh.normalize_record({
        "State": "Karnataka", "District": "Kolar", "Market": "Kolar",
        "Commodity": "Tomato", "Arrival_Date": "15/10/2026", "Modal_Price": "",
    })
    assert rec["modal_price"] is None


# ── Validation ────────────────────────────────────────────────────────────────

def _good_record(**over):
    rec = {
        "state": "Karnataka", "district": "Kolar", "market": "Kolar",
        "commodity": "Tomato", "variety": None,
        "arrival_date": datetime.date(2026, 10, 15),
        "min_price": 1500.0, "max_price": 2100.0, "modal_price": 1800.0,
        "arrivals_tonnes": 40.0,
    }
    rec.update(over)
    return rec


TODAY = datetime.date(2026, 10, 17)
WINDOW_START = TODAY - datetime.timedelta(days=10)


@pytest.mark.parametrize("bad,reason", [
    ({"arrival_date": None}, data_refresh.REJECT_BAD_DATE),
    ({"arrival_date": TODAY + datetime.timedelta(days=1)}, data_refresh.REJECT_FUTURE),
    ({"arrival_date": WINDOW_START - datetime.timedelta(days=1)}, data_refresh.REJECT_TOO_OLD),
    ({"modal_price": 0.0}, data_refresh.REJECT_BAD_PRICE),
    ({"modal_price": None}, data_refresh.REJECT_BAD_PRICE),
    ({"min_price": 1900.0}, data_refresh.REJECT_BAD_ORDER),   # min above modal
    ({"max_price": 1700.0}, data_refresh.REJECT_BAD_ORDER),   # max below modal
    ({"market": ""}, data_refresh.REJECT_MISSING),
    ({"district": None}, data_refresh.REJECT_MISSING),
    ({"state": "Maharashtra"}, data_refresh.REJECT_OTHER_MARKET),
])
def test_bad_rows_are_rejected_with_a_reason(bad, reason):
    rec = _good_record(**bad)
    got = data_refresh.validate_record(rec, window_start=WINDOW_START, today=TODAY)
    assert got == reason, f"{bad} should be rejected as {reason}, got {got!r}"


def test_good_row_passes():
    assert data_refresh.validate_record(
        _good_record(), window_start=WINDOW_START, today=TODAY) is None


def test_a_blank_price_does_not_become_zero():
    """A mandi row missing prices must be rejected, never imputed as ₹0/quintal."""
    valid, rejected = data_refresh.validate_records(
        [_good_record(modal_price=None)], window_start=WINDOW_START, today=TODAY
    )
    assert valid == []
    assert rejected[data_refresh.REJECT_BAD_PRICE] == 1


# ── Deduplication ─────────────────────────────────────────────────────────────

def test_duplicates_collapse_and_the_revision_wins():
    """
    AGMARKNET re-publishes a day with corrected figures. Storing both would
    double-count the mandi day; keeping the later row keeps the revision.
    """
    rows = [
        _good_record(modal_price=1800.0),
        _good_record(modal_price=1950.0),          # corrected re-publication
        _good_record(market="Hoskote", modal_price=1600.0),  # different mandi
    ]
    unique, dropped = data_refresh.dedupe_records(rows)
    assert dropped == 1
    assert len(unique) == 2
    by_market = {r["market"]: r for r in unique}
    assert by_market["Kolar"]["modal_price"] == 1950.0


def test_dedupe_ignores_letter_case_of_mandi_names():
    """'Kolar' and 'kolar' are the same mandi day, not two records."""
    unique, dropped = data_refresh.dedupe_records(
        [_good_record(market="Kolar"), _good_record(market="kolar")]
    )
    assert (len(unique), dropped) == (1, 1)


# ── Live PostgreSQL integration (fake fetcher, real writes) ───────────────────

def _db_reachable() -> bool:
    try:
        async def probe():
            from backend.core.database import AsyncSessionLocal
            async with AsyncSessionLocal() as db:
                await db.execute(text("SELECT 1"))
        asyncio.run(probe())
        return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(
    not _db_reachable(), reason="PostgreSQL not reachable for integration tests"
)


@pytest.fixture(scope="module", autouse=True)
def _ensure_schema():
    """Create data_refresh_runs if this checkout has not started the API yet."""
    if not _db_reachable():
        return
    import importlib
    init_db = importlib.import_module("scripts.00_init_db").init_db
    asyncio.run(init_db())


def _api_row(day: datetime.date, modal=1800.0, market=TEST_MARKET):
    """A record in the shape data.gov.in actually returns."""
    return {
        "State": "Karnataka",
        "District": TEST_DISTRICT,
        "Market": market,
        "Commodity": TEST_CROP,
        "Arrival_Date": f"{day:%d/%m/%Y}",
        "Min_Price": str(modal * 0.9),
        "Max_Price": str(modal * 1.1),
        "Modal_Price": str(modal),
    }


async def _purge():
    """Remove this test crop's rows so each run starts from a known state.

    Run records are deleted by id in each test's finally block: nothing else in
    the table can be identified as ours without reading its JSON details.
    """
    from backend.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        await db.execute(delete(MandiPrice).where(MandiPrice.commodity == TEST_CROP))
        await db.commit()


async def _purge_runs(session, run_ids):
    if run_ids:
        await session.execute(delete(DataRefreshRun).where(DataRefreshRun.id.in_(run_ids)))
        await session.commit()


async def _count_rows(session) -> int:
    return (await session.execute(
        select(func.count()).select_from(MandiPrice).where(MandiPrice.commodity == TEST_CROP)
    )).scalar() or 0


@requires_db
@pytest.mark.asyncio
async def test_refresh_lands_new_rows_and_restores_forecasting():
    """
    The core promise: a refresh that fetches current data moves the feed inside
    the SLA, so price queries stop being refused. Before it, the same probe
    reports the feed as not forecastable.
    """
    await _purge()
    from backend.core.database import AsyncSessionLocal
    run_ids: list[int] = []
    try:
        async with AsyncSessionLocal() as db:
            today = datetime.datetime.now(datetime.timezone.utc).date()

            # Only fresh rows for our test crop: the feed's newest date is the
            # global MAX, so these make the feed forecastable again.
            def fetcher(crop, ws, we):
                return [_api_row(today), _api_row(today - datetime.timedelta(days=1), modal=1750.0)]

            summary = await data_refresh.run_refresh(
                db, trigger="test", fetcher=fetcher, crops=[TEST_CROP]
            )
            run_ids.append(summary["run_id"])

            assert summary["status"] == "success"
            assert summary["rows_inserted"] == 2
            assert summary["rows_rejected"] == 0
            assert await _count_rows(db) == 2

            health = await data_refresh.data_freshness(db)
            assert health["forecastable"] is True
            assert health["age_days"] == 0
            assert health["newest_market_date"] == today.isoformat()
            assert health["last_refresh"]["status"] == "success"
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(MandiPrice).where(MandiPrice.commodity == TEST_CROP))
            await _purge_runs(db, run_ids)
            await db.commit()


@requires_db
@pytest.mark.asyncio
async def test_rerunning_a_refresh_does_not_double_count_a_mandi_day():
    """
    Same payload twice: the unique constraint plus ON CONFLICT DO NOTHING must
    make the second run a no-op, reported as no_new_data rather than success.
    """
    await _purge()
    from backend.core.database import AsyncSessionLocal
    run_ids: list[int] = []
    try:
        today = datetime.datetime.now(datetime.timezone.utc).date()

        def fetcher(crop, ws, we):
            return [_api_row(today)]

        async with AsyncSessionLocal() as db:
            first = await data_refresh.run_refresh(
                db, trigger="test", fetcher=fetcher, crops=[TEST_CROP])
            run_ids.append(first["run_id"])
            assert first["rows_inserted"] == 1

            second = await data_refresh.run_refresh(
                db, trigger="test", fetcher=fetcher, crops=[TEST_CROP])
            run_ids.append(second["run_id"])

            assert second["status"] == "no_new_data"
            assert second["rows_inserted"] == 0
            assert second["rows_fetched"] == 1        # it did read the upstream
            assert await _count_rows(db) == 1         # and still only one row
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(MandiPrice).where(MandiPrice.commodity == TEST_CROP))
            await _purge_runs(db, run_ids)
            await db.commit()


@requires_db
@pytest.mark.asyncio
async def test_failed_refresh_is_recorded_and_leaves_the_database_untouched():
    """
    An upstream error must produce a `failed` run with the error text — not an
    empty success, and not `no_new_data`, which would read as "the mandi was
    quiet" and hide a broken pipeline.
    """
    await _purge()
    from backend.core.database import AsyncSessionLocal
    run_ids: list[int] = []
    try:
        def boom(crop, ws, we):
            raise data_refresh.RefreshFetchError("HTTP 503 while fetching")

        async with AsyncSessionLocal() as db:
            before = await _count_rows(db)
            summary = await data_refresh.run_refresh(
                db, trigger="test", fetcher=boom, crops=[TEST_CROP])
            run_ids.append(summary["run_id"])

            assert summary["status"] == "failed"
            assert "HTTP 503" in summary["error"]
            assert summary["rows_inserted"] == 0
            assert await _count_rows(db) == before

            stored = (await db.execute(
                select(DataRefreshRun).where(DataRefreshRun.id == summary["run_id"])
            )).scalar_one()
            assert stored.status == "failed"
            assert stored.error == "HTTP 503 while fetching"
            assert stored.trigger == "test"
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(MandiPrice).where(MandiPrice.commodity == TEST_CROP))
            await _purge_runs(db, run_ids)
            await db.commit()


@requires_db
@pytest.mark.asyncio
async def test_rejected_rows_are_counted_not_dropped_silently():
    """A bad batch must show up in the run record with its reason."""
    await _purge()
    from backend.core.database import AsyncSessionLocal
    run_ids: list[int] = []
    try:
        today = datetime.datetime.now(datetime.timezone.utc).date()

        def fetcher(crop, ws, we):
            return [
                _api_row(today),
                _api_row(today, modal=0.0),                                   # bad price
                {**_api_row(today), "Market": "", "District": ""},            # missing fields
                {**_api_row(today), "State": "Maharashtra"},                  # wrong state
            ]

        async with AsyncSessionLocal() as db:
            summary = await data_refresh.run_refresh(
                db, trigger="test", fetcher=fetcher, crops=[TEST_CROP])
            run_ids.append(summary["run_id"])

            assert summary["rows_fetched"] == 4
            assert summary["rows_inserted"] == 1
            assert summary["rows_rejected"] == 3
            reasons = summary["rejection_reasons"]
            assert reasons[data_refresh.REJECT_BAD_PRICE] == 1
            assert reasons[data_refresh.REJECT_MISSING] == 1
            assert reasons[data_refresh.REJECT_OTHER_MARKET] == 1

            stored = (await db.execute(
                select(DataRefreshRun).where(DataRefreshRun.id == summary["run_id"])
            )).scalar_one()
            assert stored.rows_rejected == 3
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(MandiPrice).where(MandiPrice.commodity == TEST_CROP))
            await _purge_runs(db, run_ids)
            await db.commit()


@requires_db
@pytest.mark.asyncio
async def test_advisory_lock_serialises_refreshes_across_workers():
    """
    Two workers ticking at the same moment must not both hit the API. The second
    acquirer gets RefreshAlreadyRunning so the scheduler skips its turn.
    """
    from backend.core.database import engine
    with pytest.raises(data_refresh.RefreshAlreadyRunning):
        async with data_refresh.refresh_lock(engine):
            async with data_refresh.refresh_lock(engine):
                pass


@requires_db
@pytest.mark.asyncio
async def test_lock_releases_after_the_first_holder_finishes():
    """A released lock must be acquirable again — no permanent stall."""
    from backend.core.database import engine
    async with data_refresh.refresh_lock(engine):
        pass
    async with data_refresh.refresh_lock(engine):
        pass


# ── Fetch layer (no network: the transport itself is mocked) ──────────────────

@pytest.mark.asyncio
async def test_fetch_requires_an_api_key_and_says_so():
    """A missing credential is a configuration fault, raised before any request."""
    with pytest.raises(data_refresh.RefreshFetchError, match="not configured"):
        await asyncio.to_thread(
            data_refresh.fetch_window, "Tomato", WINDOW_START, TODAY, api_key=""
        )


def test_fetch_pushes_filters_to_the_server():
    """
    Incremental means the date window is a query filter. Fetching everything and
    filtering locally would re-download years of history on every tick.
    """
    captured = {}

    class Resp:
        status_code = 200
        text = ""
        def json(self):
            return {"records": []}

    class FakeSession:
        headers = {}
        def get(self, url, params=None, timeout=None):
            captured.setdefault("calls", []).append(params)
            captured["url"] = url
            return Resp()
        def close(self):
            pass

    sess = FakeSession()
    out = data_refresh.fetch_window(
        "Tomato", WINDOW_START, TODAY,
        api_key="test-key", session=sess, pace_seconds=0.0,
    )
    assert out == []
    # NIC's WAF blackholes the default python-requests UA (hangs until
    # timeout); requests.Session() pre-populates it, so only DIRECT
    # ASSIGNMENT (not setdefault) overrides it. Pin that.
    assert "python-requests" not in sess.headers.get("User-Agent", "")
    assert sess.headers["User-Agent"].startswith("Mozilla/")
    assert captured["url"].startswith("https://api.data.gov.in/resource/")
    # The resource ignores date RANGE filters (verified live 2026-10-27:
    # every `a:b`/between spelling returns zero records even for dates the
    # archive contains), so the window must be queried one equality day at
    # a time — one request per day in [WINDOW_START, TODAY].
    calls = captured["calls"]
    expected_days = (TODAY - WINDOW_START).days + 1
    assert len(calls) == expected_days
    assert calls[0]["filters[Arrival_Date]"] == f"{WINDOW_START:%d/%m/%Y}"
    assert calls[-1]["filters[Arrival_Date]"] == f"{TODAY:%d/%m/%Y}"
    params = calls[0]
    assert params["filters[State]"] == settings.refresh_state
    assert params["filters[Commodity]"] == "Tomato"
    assert params["api-key"] == "test-key"


def test_http_error_becomes_refresh_fetch_error():
    class Resp:
        status_code = 500
        text = "upstream exploded"
        def json(self):
            return {}

    class FakeSession:
        headers = {}
        def get(self, url, params=None, timeout=None):
            return Resp()
        def close(self):
            pass

    with pytest.raises(data_refresh.RefreshFetchError, match="HTTP 500"):
        data_refresh.fetch_window("Tomato", WINDOW_START, TODAY,
                                  api_key="k", session=FakeSession())


def test_rate_limit_is_reported_as_failure_not_empty_success():
    """
    A 429 is not "no data today". Silently returning [] here would classify a
    throttled pipeline as a quiet market and hide the outage.
    """
    class Resp:
        status_code = 429
        text = "too many requests"
        def json(self):
            return {}

    class FakeSession:
        headers = {}
        def get(self, url, params=None, timeout=None):
            return Resp()
        def close(self):
            pass

    with pytest.raises(data_refresh.RefreshFetchError, match="429"):
        data_refresh.fetch_window("Tomato", WINDOW_START, TODAY,
                                  api_key="k", session=FakeSession(),
                                  retry_backoff=0.0, pace_seconds=0.0)


# ── Scheduler (no network, no database) ───────────────────────────────────────

from backend.services import scheduler  # noqa: E402


class _LockBusy:
    """Stands in for refresh_lock when another worker already holds it."""
    def __init__(self, engine):
        pass
    async def __aenter__(self):
        raise data_refresh.RefreshAlreadyRunning("held elsewhere")
    async def __aexit__(self, *exc):
        return False


@pytest.mark.asyncio
async def test_refresh_once_skips_rather_than_queueing_when_locked():
    from unittest.mock import AsyncMock, patch
    with patch.object(data_refresh, "refresh_lock", _LockBusy), \
         patch.object(data_refresh, "run_refresh", AsyncMock()) as run:
        assert await scheduler.refresh_once() is None
        run.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_broken_refresh_cannot_kill_the_scheduler():
    """
    refresh_once swallows everything: an ingestion fault must not take the API
    down with it, and must not cancel the loop that is meant to retry.
    """
    from unittest.mock import patch
    class Boom:
        def __init__(self, engine): pass
        async def __aenter__(self): raise RuntimeError("disk gone")
        async def __aexit__(self, *exc): return False
    with patch.object(data_refresh, "refresh_lock", Boom):
        assert await scheduler.refresh_once() is None


def _run_loop_briefly(**overrides):
    """Start refresh_loop, let its first iteration finish, then cancel it."""
    async def go():
        task = asyncio.create_task(scheduler.refresh_loop(**overrides))
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(go())


def test_scheduler_catches_up_on_start_when_the_feed_is_stale():
    from unittest.mock import AsyncMock, patch
    with patch.object(scheduler, "is_stale", AsyncMock(return_value=True)), \
         patch.object(scheduler, "refresh_once", AsyncMock()) as once:
        _run_loop_briefly(interval_hours=99)
        once.assert_awaited_once()


def test_scheduler_does_not_spend_api_quota_when_the_feed_is_current():
    from unittest.mock import AsyncMock, patch
    with patch.object(scheduler, "is_stale", AsyncMock(return_value=False)), \
         patch.object(scheduler, "refresh_once", AsyncMock()) as once:
        _run_loop_briefly(interval_hours=99)
        once.assert_not_awaited()


def test_scheduler_is_disabled_by_configuration():
    """REFRESH_ENABLED=false must leave scheduling to cron, not start a loop."""
    from unittest.mock import patch
    with patch.object(settings, "refresh_enabled", False):
        assert scheduler.start_refresh_task() is None
