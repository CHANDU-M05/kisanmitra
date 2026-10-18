"""
tests/test_price_freshness_and_provenance.py — P0 freshness SLA + data provenance.

Closes the two gaps the October audit left open after the shared price service
landed:

  * Stale data must never be presented as today's price. Beyond the configured
    SLA the service returns type="stale_data" with the record's real age and
    refuses to forecast from it.
  * Every forecast input that had to be substituted or was missing (a tonnage
    from a different mandi or a different day, no tonnage at all, a history too
    short for real rolling features) is reported in data_quality, and arrivals
    are resolved against the SAME market the spot price came from.

Also pins the cross-channel guarantee behaviourally: WhatsApp and Telegram must
call the identical function object, not two copies of the same logic.
"""
from __future__ import annotations

import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.config import settings
from price_test_helpers import (
    arrivals_row, empty_first, history_probe, price_db, price_row, _res_with_first,
)


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
              return_value={"crop_mape_pct": 27.84, "msp_floor": None}),
    ]


async def _forecast(db, crop="Tomato", district="Kolar"):
    from backend.services.price_service import get_price_forecast

    import contextlib
    with contextlib.ExitStack() as stack:
        for p in _ml_patches():
            stack.enter_context(p)
        return await get_price_forecast(crop, district, db)


# ── Freshness SLA ─────────────────────────────────────────────────────────────

def test_default_sla_is_three_days():
    assert settings.price_max_age_days == 3


@pytest.mark.asyncio
async def test_stale_price_is_reported_not_forecast():
    """A 10-day-old record must yield stale_data — never a forecast."""
    db = price_db(price=1800.0, days_old=10)
    result = await _forecast(db)

    assert result["type"] == "stale_data"
    assert result["days_old"] == 10
    assert result["max_age_days"] == settings.price_max_age_days
    assert result["price_as_of"] == (
        datetime.date.today() - datetime.timedelta(days=10)).isoformat()
    # The last known price is disclosed WITH its date...
    assert result["current_price"] == 1800.0
    # ...but nothing here can be mistaken for a current recommendation.
    for forbidden in ("forecast", "signal", "signal_kannada", "lower", "upper"):
        assert forbidden not in result, f"stale_data must not carry {forbidden}"
    # The gate fires after the spot row plus the one feed-wide probe it needs to
    # explain itself — no arrivals or history work is wasted.
    assert db.execute.await_count == 2


@pytest.mark.asyncio
async def test_stale_reason_is_upstream_when_the_whole_feed_is_behind():
    """
    If the record we have IS the newest in the database, nothing has been
    published anywhere. Saying "ask about your crop later" would be a lie.
    """
    db = price_db(price=1800.0, days_old=20, feed_newest_days_old=20)
    result = await _forecast(db)

    assert result["stale_reason"] == "upstream_not_published"
    assert result["feed_newest_date"] == result["price_as_of"]
    assert result["feed_age_days"] == 20


@pytest.mark.asyncio
async def test_stale_reason_is_crop_gap_when_the_feed_moves_on():
    """The feed has newer data elsewhere → this crop's mandi is the gap."""
    db = price_db(price=1800.0, days_old=20, feed_newest_days_old=1)
    result = await _forecast(db)

    assert result["stale_reason"] == "crop_gap"
    assert result["feed_age_days"] == 1
    assert result["feed_newest_date"] != result["price_as_of"]


@pytest.mark.asyncio
async def test_stalled_feed_and_older_crop_are_reported_together():
    """
    The live case this deployment is actually in: the whole feed stopped 53 days
    ago AND Tomato's market stopped even earlier. Reporting only the crop gap
    would tell the farmer his mandi failed to report, when nothing did.
    """
    db = price_db(price=1800.0, days_old=143, feed_newest_days_old=53)
    result = await _forecast(db)

    assert result["stale_reason"] == "upstream_stalled_with_crop_gap"
    assert result["feed_age_days"] == 53
    assert result["days_old"] == 143

    from telegram_bot.formatters import format_result
    text = format_result(result)
    assert "data-feed delay" in text
    assert "older still" in text


@pytest.mark.asyncio
@pytest.mark.parametrize("days_old,expected_type", [
    (0, "forecast"),
    (2, "forecast"),
    (3, "forecast"),      # exactly at the SLA boundary is still acceptable
    (4, "stale_data"),    # one day past it is not
])
async def test_sla_boundary_is_inclusive(days_old, expected_type):
    db = price_db(price=2000.0, days_old=days_old)
    result = await _forecast(db)
    assert result["type"] == expected_type


@pytest.mark.asyncio
async def test_sla_is_configurable():
    """Tightening the knob must tighten behaviour — the SLA is a policy, not a constant."""
    db = price_db(price=2000.0, days_old=2)
    with patch.object(settings, "price_max_age_days", 1):
        result = await _forecast(db)
    assert result["type"] == "stale_data"
    assert result["max_age_days"] == 1


@pytest.mark.asyncio
async def test_missing_record_date_is_flagged():
    """No arrival_date → the age is unknown; that must be disclosed, not assumed fresh."""
    row = SimpleNamespace(modal_price=2000.0, arrival_date=None,
                          market="Kolar", district="Kolar")
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[
        _res_with_first(row),
        _res_with_first(arrivals_row(80.0)),
        history_probe(5),
    ])
    result = await _forecast(db)

    assert result["type"] == "forecast"          # usable price, unknown date
    assert "arrival_date_missing" in result["data_quality"]
    assert result["days_old"] is None


# ── Market-consistent inputs + degraded-data provenance ───────────────────────

@pytest.mark.asyncio
async def test_arrivals_are_resolved_against_the_spot_price_market():
    """Price from Aramane must not be blended with Kolar's arrival tonnage."""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[
        _res_with_first(price_row(2000.0, market="Aramane", district="Kolar")),
        _res_with_first(arrivals_row(42.0, market="Aramane")),
        history_probe(5),
    ])
    result = await _forecast(db, district="Kolar")

    arrivals_sql = str(db.execute.await_args_list[1].args[0]
                       .compile(compile_kwargs={"literal_binds": True}))
    assert "lower(mandi_prices.market) LIKE lower('Aramane')" in arrivals_sql
    assert "mandi_prices.district" not in arrivals_sql
    assert result["data_quality"] == []


@pytest.mark.asyncio
async def test_unrecorded_arrivals_are_disclosed_as_unknown():
    """
    No tonnage for this mandi -> 0.0 plus an explicit flag.

    The old code invented 100.0 tonnes here (and `/prices/predict` hardcoded the
    same 100.0 in its URL). Arrivals are not a feature of the deployed model, so
    the invented number changed no prediction while making the answer look like
    an observation — so it is gone rather than renamed.
    """
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[
        _res_with_first(price_row(2000.0)),
        empty_first(),            # no arrivals recorded for that market
        history_probe(5),
    ])
    result = await _forecast(db)

    assert result["type"] == "forecast"
    assert "arrivals_unknown" in result["data_quality"]
    assert result["arrivals_tonnes"] == 0.0
    assert result["arrivals_provenance"] == "unknown"
    # Exactly one arrivals query: the tonnage of a DIFFERENT mandi in the same
    # district is never substituted for the mandi whose price we are using.
    assert db.execute.await_count == 3
    assert "district" not in str(db.execute.await_args_list[1].args[0]
                                 .compile(compile_kwargs={"literal_binds": True}))


@pytest.mark.asyncio
async def test_arrival_tonnage_from_another_market_is_disclosed():
    """Defensive disclosure: a mismatched mandi on the tonnage row is visible."""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[
        _res_with_first(price_row(2000.0, market="Kolar")),
        _res_with_first(arrivals_row(90.0, market="Hoskote")),
        history_probe(5),
    ])
    result = await _forecast(db)

    assert "arrivals_other_market" in result["data_quality"]
    assert "arrivals_unknown" not in result["data_quality"]
    assert result["arrivals_provenance"] == "other_market"


@pytest.mark.asyncio
async def test_arrival_date_mismatch_is_disclosed():
    """Price from today, tonnage from last week — the blend must be visible."""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[
        _res_with_first(price_row(2000.0, days_old=0)),
        _res_with_first(arrivals_row(80.0, days_old=7)),
        history_probe(5),
    ])
    result = await _forecast(db)

    assert "arrivals_date_mismatch" in result["data_quality"]


@pytest.mark.asyncio
async def test_sparse_history_is_disclosed():
    """Below 3 records ml_service substitutes synthetic rolling features — must be flagged."""
    db = price_db(price=2000.0, history_rows=2)
    result = await _forecast(db)

    assert "history_sparse" in result["data_quality"]


@pytest.mark.asyncio
async def test_rich_history_is_not_flagged():
    db = price_db(price=2000.0, history_rows=3)
    result = await _forecast(db)

    assert "history_sparse" not in result["data_quality"]


# ── One implementation for every channel ──────────────────────────────────────

def test_whatsapp_references_the_shared_price_service():
    """Identity, not text-matching: the webhook must hold the same callable."""
    from backend.routers import webhook
    from backend.services import price_service

    assert webhook.get_price_forecast is price_service.get_price_forecast


@pytest.mark.asyncio
async def test_conversation_handler_delegates_to_shared_price_service():
    """Telegram/REST path must not keep a second copy of the forecast logic."""
    from backend.routers import conversation
    from backend.services import price_service

    db = AsyncMock()
    sentinel = {"type": "no_data", "crop": "Tomato", "district": "Kolar"}
    with patch.object(price_service, "get_price_forecast",
                      new=AsyncMock(return_value=sentinel)) as called:
        result = await conversation._handle_price("Tomato", "Kolar", db)

    called.assert_awaited_once_with("Tomato", "Kolar", db)
    assert result == sentinel


def test_no_synthetic_price_constants_remain_in_webhook():
    from pathlib import Path

    source = (Path(__file__).parents[1] / "backend/routers/webhook.py").read_text()
    assert "default_spots" not in source
    assert "1850.0" not in source


# ── Live-data types: Postgres TIMESTAMP arrives tz-aware ───────────────────

@pytest.mark.asyncio
async def test_build_features_accepts_tz_aware_timestamps():
    """
    Regression for a crash that only real Postgres data exposed.

    arrival_date is a TIMESTAMP column, so SQLAlchemy returns an aware datetime.
    The old guard `if isinstance(last_date, date)` was True for datetimes (date is
    the parent class) and then computed date - datetime -> TypeError, so every
    live price query that reached feature building raised.
    """
    from backend.services import ml_service

    aware = datetime.datetime(2026, 10, 10, 6, 0,
                              tzinfo=datetime.timezone(datetime.timedelta(hours=5, minutes=30)))

    def scalers(values):
        res = MagicMock()
        res.scalars.return_value.all.return_value = values
        return res

    hist = scalers([1500.0, 1450.0, 1400.0, 1380.0])
    prior = MagicMock()
    prior.all.return_value = [SimpleNamespace(arrival_date=aware, modal_price=1200.0)]
    arr7 = scalers([50.0, 60.0])
    last_date_res = MagicMock()
    last_date_res.scalar_one_or_none.return_value = aware

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[hist, prior, arr7, last_date_res])

    # build_features projects onto the loaded model's FEATURES list, which is
    # empty in a process that never called load_model().
    with patch.object(ml_service, "FEATURES", ["modal_price", "days_since_last_report"]):
        X = await ml_service.build_features(1400.0, 55.0, 10, "Tomato", "Kolar", db)

    # A real lag value must be produced from the aware timestamp, not an exception.
    assert X["days_since_last_report"].iloc[0] >= 0
    assert db.execute.await_count == 4


def test_age_helper_handles_date_datetime_and_string():
    from backend.services.price_service import _age_in_days

    today = datetime.date(2026, 10, 17)
    assert _age_in_days(datetime.datetime(2026, 10, 15, 18, 0), today) == 2
    assert _age_in_days(datetime.date(2026, 10, 12), today) == 5
    assert _age_in_days("2026-10-17", today) == 0
    assert _age_in_days(None, today) is None
    assert _age_in_days("not-a-date", today) is None


# ── Channel rendering of the new result types ─────────────────────────────────

def test_formatter_labels_stale_data_honestly():
    from telegram_bot.formatters import format_result

    text = format_result({
        "type": "stale_data", "crop": "Tomato", "district": "Dharwad",
        "current_price": 1800.0, "price_as_of": "2026-10-05", "days_old": 12,
        "max_age_days": 3, "source_market": "Dharwad", "data_source": "district",
        "data_quality": [],
    })
    assert "No current price" in text
    assert "12 days ago" in text
    assert "3-day freshness limit" in text
    assert "will not forecast from an old price" in text
    assert "Forecast:" not in text


def test_formatter_never_calls_an_old_price_todays_price():
    from telegram_bot.formatters import format_forecast

    stale = format_forecast({
        "crop": "Tomato", "district": "Kolar", "current_price": 2000.0,
        "forecast": 2100.0, "lower": 1700.0, "upper": 2500.0, "signal": "NEUTRAL",
        "crop_mape_pct": 27.84, "price_as_of": "2026-10-14", "days_old": 2,
        "data_source": "district", "data_quality": ["history_sparse"],
    })
    assert "Today's Price" not in stale
    assert "Latest recorded price" in stale
    assert "Spot price as of 2026-10-14 (2 days old)" in stale
    assert "trend features are estimated" in stale

    fresh = format_forecast({
        "crop": "Tomato", "district": "Kolar", "current_price": 2000.0,
        "forecast": 2100.0, "lower": 1700.0, "upper": 2500.0, "signal": "NEUTRAL",
        "crop_mape_pct": 27.84, "price_as_of": "2026-10-16", "days_old": 0,
        "data_source": "district", "data_quality": [],
    })
    assert "Today's Price" in fresh
    assert "⚠" not in fresh


# ── §5 imputed inputs: a documented reference with explicit provenance ──
#
# Saturation divides declared acreage by a reference area. The reference is a
# published statistic, not a measurement, so the response has to say which one
# it used — and the frontend must stop dividing by its own invented number.

def _sat_db(areas):
    db = MagicMock()
    res = MagicMock()
    res.scalars.return_value = MagicMock(all=lambda: areas)
    db.execute = AsyncMock(return_value=res)
    return db


@pytest.mark.asyncio
async def test_saturation_names_the_reference_area_it_divided_by():
    from backend.services import farmer_service

    farmer_service._SATURATION_CACHE.clear()
    try:
        result = await farmer_service.calc_saturation("Kolar", "Tomato", "kharif", _sat_db([6000.0]))
        assert result["reference_area_acres"] == 12000
        assert result["reference_basis"] == "district_crop_statistics"
        assert result["saturation_pct"] == 50.0
    finally:
        farmer_service._SATURATION_CACHE.clear()


@pytest.mark.asyncio
async def test_saturation_fallback_is_labelled_as_a_fallback():
    from backend.services import farmer_service

    farmer_service._SATURATION_CACHE.clear()
    try:
        result = await farmer_service.calc_saturation("Belthangady", "Tomato", "kharif", _sat_db([500.0]))
        # Nothing on record for this district/crop: the generic average is used
        # and the response says so instead of implying a measured capacity.
        assert result["reference_area_acres"] is None
        assert result["reference_basis"] == "state_average_fallback"
        assert result["saturation_pct"] == 10.0
    finally:
        farmer_service._SATURATION_CACHE.clear()
