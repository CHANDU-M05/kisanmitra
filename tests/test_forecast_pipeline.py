"""Forecast pipeline restoration — focused, no-database tests.

P0 feature-restoration task: forecasts showed NO FORECAST because the price
feed went stale. Phase 1 proved two things offline:

  1. The freshness gate itself is honest and must stay (a stale row must never
     produce a fabricated forecast) — asserted here at the router boundary.
  2. A code-level starvation defect: the ingestion window evaluated "today" in
     UTC while AGMARKNET stamps arrival dates in IST, so current Indian-date
     rows were rejected as `arrival_date_in_future` for ~5.5h every day. The
     fix (market_today) is asserted here on both sides of the pipeline:
     ingestion window and read-side age.

Every test runs with mocked sessions/models — no database, no network, no
production endpoints.
"""
from __future__ import annotations

import contextlib
import datetime
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "backend", ROOT / "backend" / "services", ROOT / "tests", ROOT):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

from backend.core.config import settings
from backend.core.database import get_db
from backend.routers import prices
from backend.services import data_refresh, price_service
from price_test_helpers import market_db, market_day


# ── The market clock ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("utc_now,expected", [
    # Normal case: same calendar day in both zones.
    (datetime.datetime(2026, 11, 3, 12, 0, tzinfo=datetime.timezone.utc),
     datetime.date(2026, 11, 3)),
    # THE DEFECT WINDOW: UTC still says "2nd", the market is already on "3rd"
    # and has published rows dated 3rd. 20:00 UTC = 01:30 IST next day.
    (datetime.datetime(2026, 11, 2, 20, 0, tzinfo=datetime.timezone.utc),
     datetime.date(2026, 11, 3)),
    # Boundary: 05:30 IST is the instant the two calendars realign.
    (datetime.datetime(2026, 11, 2, 0, 0, tzinfo=datetime.timezone.utc),
     datetime.date(2026, 11, 2)),
    (datetime.datetime(2026, 11, 2, 0, 30, tzinfo=datetime.timezone.utc),
     datetime.date(2026, 11, 2)),
    # A naive datetime is treated as UTC, never as an unknown local time.
    (datetime.datetime(2026, 11, 2, 20, 0),
     datetime.date(2026, 11, 3)),
])
def test_market_today_follows_the_indian_calendar(utc_now, expected):
    assert data_refresh.market_today(utc_now) == expected


@pytest.mark.asyncio
async def test_ingestion_window_end_is_the_market_date_by_default():
    """run_refresh's default `today` must come from the market clock.

    On a UTC host the two calendars only diverge during 18:30–24:00 UTC, so
    the assertion is written against `market_today()` itself, not the wall
    clock, and the fetch window is captured through the injectable fetcher.
    """
    db = AsyncMock()
    db.add = MagicMock()          # sync on the real session; AsyncMock would dangle
    captured: list[tuple] = []

    def fetcher(crop, window_start, window_end):
        captured.append((window_start, window_end))
        return []

    with patch.object(data_refresh, "get_newest_date", AsyncMock(return_value=None)), \
         patch.object(data_refresh, "existing_keys", AsyncMock(return_value=set())), \
         patch.object(data_refresh, "upsert_records", AsyncMock(return_value=0)):
        summary = await data_refresh.run_refresh(
            db, fetcher=fetcher, crops=["Tomato"], api_key="k"
        )

    assert captured, "the fetcher must have been called with a window"
    window_start, window_end = captured[0]
    assert window_end == data_refresh.market_today(), (
        "the fetch window must end at the Indian market date, not the UTC date"
    )
    assert window_start == window_end - datetime.timedelta(
        days=settings.refresh_lookback_days)
    assert summary["window_end"] == data_refresh.market_today().isoformat()


# ── The future-reject boundary (the starvation defect) ────────────────────────

def _row_dated(d: datetime.date) -> dict:
    return {
        "state": "Karnataka", "district": "Kolar", "market": "Kolar",
        "commodity": "Tomato", "variety": None, "arrival_date": d,
        "min_price": 1500.0, "max_price": 2100.0, "modal_price": 1800.0,
        "arrivals_tonnes": 40.0,
    }


@pytest.mark.parametrize("instant", [
    # 20:00 UTC on 2026-11-02 — a production evening: market date is already
    # 2026-11-03 and AGMARKNET has published 03/11/2026 rows.
    datetime.datetime(2026, 11, 2, 20, 0, tzinfo=datetime.timezone.utc),
    # 00:30 UTC — inside the old reject window too (05:30 IST = 00:00 UTC day).
    datetime.datetime(2026, 11, 3, 0, 30, tzinfo=datetime.timezone.utc),
])
def test_a_current_market_date_row_is_never_rejected_as_future(instant):
    """The P0 starvation bug, as a permanent regression test.

    Before the fix `run_refresh` used the UTC date as `today`, so at these
    instants a legitimate current row answered REJECT_FUTURE and the feed
    slowly fell out of the freshness SLA — surfacing days later in the UI as
    NO FORECAST.
    """
    ist_today = data_refresh.market_today(instant)
    utc_today = instant.astimezone(datetime.timezone.utc).date()
    window_start = ist_today - datetime.timedelta(days=settings.refresh_lookback_days)

    # Old frame: the same row was rejected (only meaningful when the two
    # calendars actually differ at this instant).
    if utc_today != ist_today:
        assert data_refresh.validate_record(
            _row_dated(ist_today), window_start=window_start, today=utc_today
        ) == data_refresh.REJECT_FUTURE

    # Fixed frame: accepted.
    assert data_refresh.validate_record(
        _row_dated(ist_today), window_start=window_start, today=ist_today
    ) is None


def test_the_future_reject_still_bites_one_day_past_the_market_date():
    """The fix moved the boundary to the market calendar; it did not remove it."""
    ist_today = data_refresh.market_today()
    window_start = ist_today - datetime.timedelta(days=settings.refresh_lookback_days)
    assert data_refresh.validate_record(
        _row_dated(ist_today + datetime.timedelta(days=1)),
        window_start=window_start, today=ist_today) == data_refresh.REJECT_FUTURE


# ── Read side: the gate measures age in the same frame ────────────────────────

def test_record_age_is_measured_on_the_market_calendar():
    """A row dated 'today' in the market frame is age 0 even when the host
    clock still says yesterday (UTC evening). Negative ages used to slip a
    not-yet-published row past the gate; inflated ages used to withhold a
    fresh one."""
    ist_today = data_refresh.market_today()
    utc_today = datetime.datetime.now(datetime.timezone.utc).date()
    host_frame_age = utc_today.toordinal() - ist_today.toordinal()  # 0 or -1
    # The service must answer 0 regardless of which frame the host keeps.
    assert price_service.record_age_days(ist_today) == 0
    if host_frame_age == -1:  # only during 18:30–24:00 UTC; assert the fix
        assert price_service.record_age_days(ist_today) != host_frame_age


def test_market_day_fixtures_land_on_the_intended_market_date():
    assert market_day(0).date() == data_refresh.market_today()
    assert market_day(3).date() == data_refresh.market_today() - datetime.timedelta(days=3)


# ── The gate itself stays (NO FORECAST is honest, not broken) ─────────────────

def _ml_patches():
    return [
        patch("backend.services.ml_service.MODEL", new=MagicMock()),
        patch("backend.services.ml_service.build_features",
              new_callable=AsyncMock, return_value={}),
        patch("backend.services.ml_service.make_prediction",
              return_value={"pred": 2100.0, "low": 1700.0, "high": 2500.0}),
        patch("backend.services.ml_service.price_signal",
              return_value=("NEUTRAL — Monitor weekly", "ಸ್ಥಿರ")),
        patch("backend.services.ml_service.crop_prediction_meta",
              return_value={"crop_mape_pct": 27.84, "msp_floor": None, "msp_ratio": None}),
    ]


def _client(db) -> TestClient:
    app = FastAPI()
    app.include_router(prices.router)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, raise_server_exceptions=True)


@contextlib.contextmanager
def _predict_client(db):
    with contextlib.ExitStack() as stack:
        for p in _ml_patches():
            stack.enter_context(p)
        yield _client(db)


def test_stale_feed_refuses_instead_of_fabricating():
    """The freshness safeguard is preserved: a 7-day-old row produces no
    forecast, no zero, and a machine-readable honest refusal."""
    db = market_db(price=1800.0, days_old=7, feed_newest_days_old=7)
    with _predict_client(db) as client:
        body = client.get("/prices/predict?commodity=Tomato&market=Kolar").json()
    assert body["type"] == "stale_data"
    assert body["predicted_price"] is None
    assert body["days_old"] == 7
    assert body["price_as_of"] == market_day(7).date().isoformat()
    assert body["feed_age_days"] == 7


def test_valid_fresh_data_reaches_the_prediction_path():
    db = market_db(price=2000.0, days_old=1)
    with _predict_client(db) as client:
        body = client.get("/prices/predict?commodity=Tomato&market=Kolar").json()
    assert body["type"] == "forecast"
    assert body["predicted_price"] == 2100.0
    assert body["confidence_low"] == 1700.0
    assert body["confidence_high"] == 2500.0
    assert body["signal"]


def test_missing_historical_record_is_reported_missing_not_priced():
    db = market_db(found=False)
    with _predict_client(db) as client:
        body = client.get("/prices/predict?commodity=Tomato&market=Kolar").json()
    assert body["type"] == "no_data"
    assert body.get("predicted_price") in (None,)


def test_model_failure_is_an_error_state_distinct_from_stale_and_missing():
    """A loaded-but-failing model must not be disguised as stale or no_data."""
    db = market_db(price=2000.0, days_old=1)
    with contextlib.ExitStack() as stack:
        for p in _ml_patches()[:2]:
            stack.enter_context(p)
        stack.enter_context(patch("backend.services.ml_service.make_prediction",
                                  side_effect=ValueError("implausible prediction")))
        client = _client(db)
        resp = client.get("/prices/predict?commodity=Tomato&market=Kolar")
    assert resp.status_code == 503
    assert "detail" in resp.json()


# ── Frontend wiring: an endpoint that answers 200 is not a working feature ────

def test_terminal_forecast_screen_is_wired_to_the_real_contract():
    from pathlib import Path as _P
    src = _P(__file__).resolve().parents[1] / "frontend" / "src" / "pages" / "TerminalView.jsx"
    text = src.read_text(encoding="utf-8")
    # Correct endpoint...
    assert "/prices/predict?commodity=" in text and "apiUrl(" in text
    # ...parsed through the honest state mapper, not raw fields...
    assert "deriveForecastView" in text
    # ...which knows the real response `type` vocabulary of the backend.
    mapper = (_P(__file__).resolve().parents[1] / "frontend" / "src" / "forecastState.js").read_text(encoding="utf-8")
    for t in ("forecast", "anomaly_flagged", "stale_data", "no_data"):
        assert f"'{t}'" in mapper or f'"{t}"' in mapper, f"mapper lost state {t}"
    # Staleness is shown WITH its age and never as a zero price.
    assert "NO FORECAST" in mapper
    assert "days old" in mapper or "day old" in mapper
