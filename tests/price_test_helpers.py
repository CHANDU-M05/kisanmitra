"""
tests/price_test_helpers.py — Shared mocks for the price_service query shape.

price_service.get_price_forecast issues a fixed sequence of queries:
  1. spot-price row        -> .first()  (modal_price, arrival_date, market, district)
  1b. state-wide fallback  -> .first()  (only when 1 returns None)
  1c. feed-newest probe    -> .scalar_one_or_none()  (only when the SLA gate fires)
  2. arrivals row          -> .first()  (by the RESOLVED MARKET only)
  3. history count probe   -> .all()    (>=3 rows keeps ml_service off its synthetic branch)
  4. distribution probe    -> .one()    (min/max/avg/stddev/count for the two-year
                                         credibility gate on the published forecast)

Dates are expressed as days_old relative to TODAY because the freshness SLA gate
actively rejects stale fixtures — a hard-coded October date silently becomes a
lie the moment the suite runs in November. "Today" is the MARKET calendar (IST),
the same frame the service and the ingestion window use, so the suite is honest
on a UTC host at UTC evening exactly as on an IST host.
"""
from __future__ import annotations

import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from backend.core.config import settings
from backend.services.data_refresh import MARKET_TZ, market_today


def market_day(days_old: int = 0) -> datetime.datetime:
    """Midnight of the market date `days_old` back, as a tz-aware datetime.

    Fixtures must be anchored to IST (the calendar AGMARKNET stamps rows with),
    not to the host clock — otherwise a UTC host in the evening measures every
    fixture a day younger than the service does.
    """
    return datetime.datetime.combine(market_today() - datetime.timedelta(days=days_old),
                                     datetime.time(), tzinfo=MARKET_TZ)

# ── Row builders ──────────────────────────────────────────────────────────────

def price_row(modal_price, market="Kolar", district="Kolar", days_old=0):
    return SimpleNamespace(
        modal_price=modal_price,
        arrival_date=market_day(days_old),
        market=market,
        district=district,
    )


def arrivals_row(tonnes, market="Kolar", days_old=0):
    return SimpleNamespace(
        arrivals_tonnes=tonnes,
        arrival_date=market_day(days_old),
        market=market,
    )


# ── Result-mock builders ──────────────────────────────────────────────────────

def _res_with_first(row) -> MagicMock:
    res = MagicMock()
    res.first.return_value = row
    return res


def empty_first() -> MagicMock:
    """A query that matched nothing: .first() -> None."""
    return _res_with_first(None)


def history_probe(n_rows: int = 5) -> MagicMock:
    res = MagicMock()
    res.all.return_value = [SimpleNamespace(modal_price=1000.0)] * n_rows
    return res


def feed_newest_res(days_old: int = 0) -> MagicMock:
    """
    Result of the feed-wide MAX(arrival_date) probe.

    The service runs it only when it is about to refuse a forecast, to decide
    whether the whole feed is behind (upstream outage) or just this crop.
    """
    res = MagicMock()
    res.scalar_one_or_none.return_value = market_day(days_old)
    return res


def dist_probe(price=1000.0, records: int = 50, low_ratio=0.5,
               high_ratio=2.0) -> MagicMock:
    """
    Result of the two-year price-distribution probe the forecast credibility
    gate reads (min, max, avg, stddev, count).

    The default describes an ordinary market: the fixture price sits mid-range
    with history spanning half to double it, so a plausible forecast passes and
    a caller can force the warning path by narrowing low_ratio/high_ratio.
    """
    res = MagicMock()
    res.one.return_value = (price * low_ratio, price * high_ratio, price,
                            price * 0.1, records)
    return res


def price_db(price=2000.0, arrivals=80.0, days_old=0, market="Kolar",
             district="Kolar", history_rows=5, arrivals_days_old=None,
             feed_newest_days_old=None):
    """
    AsyncMock DB for a district-hit price query.

    Fresh record  -> 3 queries (price, arrivals, history).
    Stale record  -> 2 queries (price, feed-newest probe); the SLA gate returns
    before touching arrivals, which is exactly what the tests should prove.
    """
    if arrivals_days_old is None:
        arrivals_days_old = days_old
    if feed_newest_days_old is None:
        feed_newest_days_old = days_old

    spot = _res_with_first(price_row(price, market, district, days_old))
    if days_old > settings.price_max_age_days:
        seq = [spot, feed_newest_res(feed_newest_days_old)]
    else:
        seq = [
            spot,
            _res_with_first(arrivals_row(arrivals, market, arrivals_days_old)),
            history_probe(history_rows),
            dist_probe(price),
        ]
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=seq)
    db.add = MagicMock()
    db.commit = AsyncMock()
    return db


def price_db_state_fallback(price=1500.0, arrivals=60.0, days_old=0,
                           state_market="Chikkaballapur", history_rows=5):
    """District miss then state-wide hit: 4 queries (price x2, arrivals, history).

    The default fallback mandi is one the model was trained on. That matters:
    against an untrained mandi the service legitimately refuses with
    type="unsupported_vocabulary", so a test that forgot to override this would
    be exercising the refusal instead of the fallback labelling it claims to
    test. Tests that want the refusal pass an untrained name explicitly.
    """
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[
        empty_first(),
        _res_with_first(price_row(price, state_market, "Karnataka", days_old)),
        _res_with_first(arrivals_row(arrivals, state_market, days_old)),
        history_probe(history_rows),
        dist_probe(price),
    ])
    db.add = MagicMock()
    db.commit = AsyncMock()
    return db


def price_db_no_data() -> AsyncMock:
    """Both spot-price queries miss; the service must refuse before any other query."""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[empty_first(), empty_first()])
    db.add = MagicMock()
    db.commit = AsyncMock()
    return db


# ── Market-scoped lookups (price_service.get_market_forecast) ─────────────────

def market_row(price=2000.0, market="Kolar", district="Kolar", days_old=0,
               arrivals=80.0):
    """
    Row as returned by get_market_forecast: price, date, market, district AND
    the tonnage all arrive in ONE query, so no cross-market blend is possible.
    """
    return SimpleNamespace(
        modal_price=price,
        arrival_date=market_day(days_old),
        market=market,
        district=district,
        arrivals_tonnes=arrivals,
    )


def market_db(price=2000.0, days_old=0, arrivals=80.0, market="Kolar",
              district="Kolar", history_rows=5, feed_newest_days_old=None,
              found=True):
    """
    AsyncMock DB for a named-mandi lookup.

    Fresh row    -> 3 queries (spot+tonnage in one row, history probe, distribution).
    Stale row    -> 2 queries (spot, feed-newest probe) and no history work.
    Missing row  -> 1 query, then the service must refuse to invent a price.
    """
    db = AsyncMock()
    if not found:
        seq = [empty_first()]
    elif days_old > settings.price_max_age_days:
        seq = [market_res(market_row(price, market, district, days_old, arrivals)),
               feed_newest_res(feed_newest_days_old
                               if feed_newest_days_old is not None else days_old)]
    else:
        seq = [market_res(market_row(price, market, district, days_old, arrivals)),
               history_probe(history_rows),
               dist_probe(price)]
    db.execute = AsyncMock(side_effect=seq)
    db.add = MagicMock()
    db.commit = AsyncMock()
    return db


def market_res(row) -> MagicMock:
    """Result mock carrying arrivals_tonnes, which the spot row also selects."""
    res = MagicMock()
    res.first.return_value = row
    return res
