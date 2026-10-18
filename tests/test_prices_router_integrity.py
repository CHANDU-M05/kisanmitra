"""
tests/test_prices_router_integrity.py — /prices/* is no longer a bypass.

The October audit found that the dashboard's prediction surface ignored every
safeguard the shared price service had gained:

  * `/prices/predict` forecasted from a caller-supplied `current_price` with no
    record lookup and no freshness check, and defaulted `arrivals_tonnes` to a
    hardcoded 100.0.
  * `/prices/history/{market}/{commodity}` answered "no data" with a synthetic
    series dated over the recent days, and the dashboard fed its last point to
    `/predict` as if it were today's mandi rate.
  * `/prices/latest-watch` invented rupee amounts (Tomato 1720, …) for crops it
    had found no rows for.

These tests drive the real ASGI routes with a mocked session, so the guards are
proven at the server boundary rather than in the browser.
"""
from __future__ import annotations

import contextlib
import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.config import settings
from backend.core.database import get_db
from backend.routers import prices
from price_test_helpers import empty_first, history_probe, market_db, market_res, market_row


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


# ── /prices/predict — freshness gate at the server boundary ───────────────────

def test_predict_gates_a_stale_mandi_record():
    """A 10-day-old mandi row yields stale_data, never a prediction."""
    db = market_db(price=1800.0, days_old=10, feed_newest_days_old=10)
    with _predict_client(db) as client:
        body = client.get("/prices/predict?commodity=Tomato&market=Kolar").json()

    assert body["type"] == "stale_data"
    assert body["predicted_price"] is None
    assert body["confidence_low"] is None
    assert body["confidence_high"] is None
    assert body["signal"] is None
    assert body["days_old"] == 10
    assert body["max_age_days"] == settings.price_max_age_days
    assert body["price_as_of"] == (
        datetime.date.today() - datetime.timedelta(days=10)).isoformat()
    assert body["stale_reason"] == "upstream_not_published"
    assert "forecast" not in body and "lower" not in body


def test_predict_refuses_a_stale_record_even_when_the_url_supplies_a_price():
    """
    The bypass this endpoint used to offer: put a price in the query string and
    get a forecast with no record check at all. `current_price` is now only a
    scenario, and a stale base price stays stale however you edit the URL.
    """
    db = market_db(price=1800.0, days_old=40, feed_newest_days_old=40)
    with _predict_client(db) as client:
        body = client.get(
            "/prices/predict?commodity=Tomato&market=Kolar"
            "&current_price=2500&arrivals_tonnes=100.0"
        ).json()

    assert body["type"] == "stale_data"
    assert body["predicted_price"] is None
    # The refusal quotes the verified mandi price, not the one in the URL.
    assert body["current_price"] == 1800.0


def test_predict_with_no_record_reports_no_data_instead_of_inventing_a_price():
    db = market_db(found=False)
    with _predict_client(db) as client:
        body = client.get("/prices/predict?commodity=Tomato&market=Kolar").json()

    assert body["type"] == "no_data"
    assert body["predicted_price"] is None
    assert body["current_price"] is None
    # No price exists, so no provenance may be claimed for one either.
    assert body["price_provenance"] is None
    assert "No mandi record" in body["message"]
    # One lookup, then a refusal — no feature building on an invented number.
    assert db.execute.await_count == 1


def test_predict_fresh_record_keeps_the_legacy_dashboard_fields():
    """Backward compatibility: the keys TerminalView already reads still exist."""
    db = market_db(price=2000.0, days_old=0, arrivals=80.0)
    with _predict_client(db) as client:
        body = client.get("/prices/predict?commodity=Tomato&market=Kolar").json()

    assert body["type"] == "forecast"
    assert body["predicted_price"] == 2100.0
    assert body["confidence_low"] == 1700.0
    assert body["confidence_high"] == 2500.0
    assert body["signal"] == "NEUTRAL — Monitor weekly"
    assert body["crop_mape_pct"] == 27.84
    assert body["current_price"] == 2000.0
    assert body["price_provenance"] == "verified_mandi"
    assert body["arrivals_tonnes"] == 80.0
    assert body["arrivals_provenance"] == "recorded"
    assert body["data_quality"] == []


def test_predict_treats_a_caller_price_as_a_labelled_scenario():
    db = market_db(price=2000.0, days_old=0)
    with _predict_client(db) as client:
        body = client.get(
            "/prices/predict?commodity=Tomato&market=Kolar&current_price=2050"
        ).json()

    assert body["type"] == "forecast"
    assert body["price_provenance"] == "caller_scenario"
    assert body["data_source"] == "caller_scenario"
    assert body["current_price"] == 2050.0
    assert "price_override" in body["data_quality"]


def test_predict_flags_a_scenario_far_from_the_verified_mandi_price():
    db = market_db(price=2000.0, days_old=0)
    with _predict_client(db) as client:
        body = client.get(
            "/prices/predict?commodity=Tomato&market=Kolar&current_price=3000"
        ).json()

    assert "price_diverges_from_mandi" in body["data_quality"]


def test_predict_labels_caller_supplied_arrivals_as_a_scenario():
    db = market_db(price=2000.0, days_old=0, arrivals=80.0)
    with _predict_client(db) as client:
        body = client.get(
            "/prices/predict?commodity=Tomato&market=Kolar&arrivals_tonnes=5000"
        ).json()

    assert body["arrivals_tonnes"] == 5000.0
    assert body["arrivals_provenance"] == "caller_scenario"
    assert "arrivals_override" in body["data_quality"]


def test_predict_discloses_unrecorded_arrivals_instead_of_defaulting_to_100():
    row = market_row(price=2000.0, days_old=0, arrivals=None)
    db = market_db(price=2000.0, days_old=0)
    db.execute = AsyncMock(side_effect=[market_res(row), history_probe(5)])
    with _predict_client(db) as client:
        body = client.get("/prices/predict?commodity=Tomato&market=Kolar").json()

    assert body["arrivals_tonnes"] == 0.0
    assert body["arrivals_provenance"] == "unknown"
    assert "arrivals_unknown" in body["data_quality"]


@pytest.mark.parametrize("query,reason", [
    ("commodity=Tomato&market=Kolar&current_price=0", "zero price"),
    ("commodity=Tomato&market=Kolar&current_price=-5", "negative price"),
    ("commodity=Tomato&market=Kolar&arrivals_tonnes=-1", "negative arrivals"),
    ("commodity=Tomato&market=Kolar&arrivals_tonnes=1e12", "absurd arrivals"),
    ("market=Kolar", "missing crop"),
    ("commodity=Tomato", "missing market"),
    ("commodity=T&market=Kolar", "one-character crop"),
])
def test_predict_rejects_invalid_parameters_before_touching_the_database(query, reason):
    """Ranges/lengths are validated server-side, so garbage never reaches the model."""
    db = market_db()
    with _predict_client(db) as client:
        res = client.get(f"/prices/predict?{query}")
    assert res.status_code == 422, reason
    assert db.execute.await_count == 0


def test_predict_returns_503_when_the_model_is_not_loaded():
    db = market_db()
    with contextlib.ExitStack() as stack:
        for p in _ml_patches():
            stack.enter_context(p)
        stack.enter_context(patch("backend.services.ml_service.MODEL", new=None))
        client = _client(db)
        assert client.get("/prices/predict?commodity=Tomato&market=Kolar").status_code == 503


# ── /prices/history — observed rows only ──────────────────────────────────────

def _history_db(rows):
    res = MagicMock()
    res.all.return_value = rows
    db = AsyncMock()
    db.execute = AsyncMock(return_value=res)
    return db


def test_history_returns_only_real_rows_and_labels_them_non_synthetic():
    ns = datetime.datetime(2026, 10, 1, 6, 0)
    db = _history_db([
        MagicMock(arrival_date=ns, modal_price=1450.0),
        MagicMock(arrival_date=datetime.date(2026, 10, 2), modal_price=1500.0),
    ])
    body = _client(db).get("/prices/history/Kolar/Tomato").json()

    assert [r["price"] for r in body] == [1450.0, 1500.0]
    assert all(r["is_synthetic"] is False for r in body)
    assert body[1]["date"] == "2026-10-02"


def test_history_never_falls_back_to_a_synthetic_series():
    """
    The fabricated series was the origin of the dashboard's fake "live" price:
    its last element was dated today and was sent to /predict as current_price.
    """
    db = _history_db([])
    with patch("backend.services.ml_service.generate_sample_history") as synth:
        body = _client(db).get("/prices/history/Kolar/Tomato").json()

    assert body == []
    synth.assert_not_called()


def test_history_bounds_the_window_and_filters_missing_prices():
    db = _history_db([])
    _client(db).get("/prices/history/Kolar/Tomato", params={"days": 30}).json()

    sql = str(db.execute.await_args.args[0].compile(
        compile_kwargs={"literal_binds": True}))
    assert "mandi_prices.arrival_date >=" in sql
    assert "modal_price IS NOT NULL" in sql
    assert "LIKE" in sql  # market/commodity are matched, not equality-only


# ── /prices/latest-watch — no invented rupee amounts ──────────────────────────

def _watch_db(pairs):
    """`pairs` = [(latest_row_or_None, prior_row_or_None), ...] one per crop."""
    seq = []
    for latest, prior in pairs:
        seq.append(market_res(latest) if latest is not None else empty_first())
        seq.append(market_res(prior) if prior is not None else empty_first())
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=seq)
    return db


def test_latest_watch_reports_no_data_rather_than_a_reference_price():
    db = _watch_db([(None, None)] * 7)
    body = _client(db).get("/prices/latest-watch").json()

    assert len(body) == 7
    assert all(item["price"] is None for item in body)
    assert all(item["state"] == "NO_DATA" for item in body)
    assert all(item["as_of"] is None for item in body)


def test_latest_watch_no_longer_contains_hardcoded_reference_prices():
    """
    Structural guard, checked on the AST so it cannot be satisfied by deleting a
    comment: no fabricated rupee constant, no synthetic-history call, and no
    reference-price dict may exist anywhere in this router.
    """
    import ast
    from pathlib import Path

    tree = ast.parse((Path(__file__).parents[1] / "backend/routers/prices.py").read_text())

    numbers = {c.value for c in ast.walk(tree)
               if isinstance(c, ast.Constant) and isinstance(c.value, (int, float))}
    fabricated = {1720, 1580, 2100, 3850, 1200, 900, 100.0}
    assert not numbers & fabricated, f"invented market values in prices.py: {numbers & fabricated}"

    names = {f"{n.func.value.id}.{n.func.attr}" for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and isinstance(n.func.value, ast.Name)}
    assert "ml_service.generate_sample_history" not in names

    assigned = {t.id for st in ast.walk(tree) if isinstance(st, ast.Assign)
                for t in st.targets if isinstance(t, ast.Name)}
    assert "base_prices" not in assigned


def test_latest_watch_reports_the_real_date_and_flags_it_stale():
    latest = market_row(price=1800.0, market="Kolar", days_old=53, arrivals=100.0)
    prior = MagicMock(modal_price=1700.0)
    db = _watch_db([(latest, prior)] * 7)
    body = _client(db).get("/prices/latest-watch").json()

    assert body[0]["price"] == 1800.0
    assert body[0]["days_old"] == 53
    assert body[0]["stale"] is True
    assert body[0]["state"] == "STALE"
    # A real movement is still reported, with the date it is measured against.
    assert body[0]["delta"] == 100.0
    assert body[0]["as_of"] == (
        datetime.date.today() - datetime.timedelta(days=53)).isoformat()


def test_latest_watch_delta_comes_from_the_same_mandi_only():
    """
    The old code took the two newest rows for a crop regardless of mandi, so a
    "daily change" was often the gap between two different markets.
    """
    latest = market_row(price=1800.0, market="Kolar", days_old=1)

    db = _watch_db([(latest, None)] * 7)
    body = _client(db).get("/prices/latest-watch").json()

    assert body[0]["delta"] is None
    assert body[0]["state"] == "UNKNOWN"
    assert "same mandi" in body[0]["note"]
    prior_sql = str(db.execute.await_args_list[1].args[0].compile(
        compile_kwargs={"literal_binds": True}))
    assert "Kolar" in prior_sql and "mandi_prices.market" in prior_sql


# ── Untouched option routes stay working (regression) ─────────────────────────

def test_crops_markets_still_falls_back_to_picker_options_not_prices():
    res = MagicMock()
    res.all.return_value = []
    db = AsyncMock()
    db.execute = AsyncMock(return_value=res)
    body = _client(db).get("/prices/crops-markets").json()

    assert "Tomato" in body["crops"] and "Kolar" in body["markets"]


def test_districts_still_returns_canonical_names_when_table_is_empty():
    empty = MagicMock()
    empty.all.return_value = []
    db = AsyncMock()
    db.execute = AsyncMock(return_value=empty)
    body = _client(db).get("/prices/districts").json()

    assert "Kolar" in body["districts"]
