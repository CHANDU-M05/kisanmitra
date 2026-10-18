"""
backend/routers/prices.py — REST price surface for the React dashboard.

This file used to contain a SECOND, UNGATED implementation of forecasting:
`/predict` took whatever `current_price` the caller put in the URL, skipped any
record lookup, skipped the freshness SLA, and defaulted `arrivals_tonnes` to a
hardcoded 100.0. The dashboard fed it a price drawn from a *synthetic* history
fallback and rendered the result as a live prediction. Every route here now
either reads real MandiPrice rows or returns an explicit no-data/stale state —
and the forecast logic itself lives in `price_service`, so the bot and the
dashboard cannot disagree about what counts as a current price.

Contract notes for API consumers (intentional changes, all additive or
documented):
  * `/predict` keeps its legacy field names (predicted_price, confidence_low,
    confidence_high, signal, ...) but `predicted_price` is now `null` whenever
    no forecast was produced, instead of a fabricated number.
  * `/predict` no longer requires `current_price`; a supplied value is treated
    as a labelled what-if scenario (`price_provenance="caller_scenario"`),
    never as a verified observation.
  * `/history` returns only rows that exist in the database; an empty array
    means "no data", not "here is a made-up series".
  * `/latest-watch` never invents a rupee amount: an unavailable price is
    `price: null` with `state: "NO_DATA"`.
"""
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.models import MandiPrice
from backend.services import price_service

router = APIRouter(prefix="/prices", tags=["prices"])


def _date_of(value) -> str | None:
    """arrival_date reaches us as date, datetime or str depending on driver."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def _predict_response(res: dict) -> dict:
    """
    Map the shared price contract onto the field names the dashboard reads.

    Kept as a thin view so `/predict` cannot grow its own freshness rules again.
    """
    data_source = res.get("data_source")
    shape = {
        "commodity":      res.get("crop"),
        "market":         res.get("market"),
        "district":       res.get("district"),
        "type":           res["type"],
        "current_price":  res.get("current_price"),
        "price_as_of":    res.get("price_as_of"),
        "days_old":       res.get("days_old"),
        "data_source":    data_source,
        "source_market":  res.get("source_market"),
        "data_quality":   res.get("data_quality", []),
        "arrivals_tonnes":     res.get("arrivals_tonnes"),
        "arrivals_provenance": res.get("arrivals_provenance"),
        # The price came from a verified mandi row, or it came from the query
        # string and is a scenario. Nothing in between — and when there is no
        # price at all, there is no provenance to claim either.
        "price_provenance": (
            None if res.get("current_price") is None
            else ("caller_scenario" if data_source == "caller_scenario"
                  else "verified_mandi")
        ),
        "crop_mape_pct":  res.get("crop_mape_pct"),
        "msp_floor":      res.get("msp_floor"),
        "msp_ratio":      res.get("msp_ratio"),
    }

    if res["type"] in ("forecast", "anomaly_flagged"):
        shape.update({
            "predicted_price": res["forecast"],
            "confidence_low":  res["lower"],
            "confidence_high": res["upper"],
            "signal":          res["signal"],
            "signal_kannada":  res["signal_kannada"],
            "is_anomaly":      res["is_anomaly"],
            "anomaly_type":    res["anomaly_type"],
            "deviation_pct":   res["deviation_pct"],
        })
        return shape

    # No forecast was produced: say so with nulls rather than a plausible number.
    shape.update({
        "predicted_price": None,
        "confidence_low":  None,
        "confidence_high": None,
        "signal":          None,
        "signal_kannada":  None,
        "is_anomaly":      False,
        "anomaly_type":    None,
        "deviation_pct":   None,
    })
    if res["type"] == "stale_data":
        shape.update({
            "max_age_days":     res["max_age_days"],
            "stale_reason":     res["stale_reason"],
            "feed_newest_date": res["feed_newest_date"],
            "feed_age_days":    res["feed_age_days"],
            "message": (
                f"Latest verified price for this mandi is from {res['price_as_of']} "
                f"({res['days_old']} days old), beyond the "
                f"{res['max_age_days']}-day freshness limit. No forecast is produced "
                "from a stale price."
            ),
        })
    elif res["type"] == "no_data":
        shape["message"] = (
            "No mandi record found in the database for this crop and market, so "
            "there is no price to forecast from."
        )
    elif res["type"] == "error":
        shape["message"] = res.get("detail")
    return shape


@router.get("/predict")
async def predict_price(
    commodity: str = Query(..., min_length=2, max_length=60),
    market: str = Query(..., min_length=2, max_length=60),
    # Optional and explicitly a scenario: a query parameter is a hypothesis, not
    # an observation. Omitting it is the normal case for a live forecast.
    current_price: float | None = Query(None, gt=0, le=1_000_000),
    arrivals_tonnes: float | None = Query(None, ge=0, le=10_000_000),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await price_service.get_market_forecast(
        commodity.strip(), market.strip(), db,
        scenario_price=current_price, scenario_arrivals=arrivals_tonnes,
    )
    if result["type"] == "error":
        raise HTTPException(503, result["detail"])
    return _predict_response(result)


@router.get("/history/{market}/{commodity}")
async def price_history(
    market: str,
    commodity: str,
    days: int = Query(default=60, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """
    Observed prices only. An empty array means the database has no rows.

    The old fallback here called `ml_service.generate_sample_history()`, which
    returns seasonal constants plus Gaussian noise DATED AS THE LAST `days`
    DAYS. The dashboard took its last element as today's spot price and sent it
    to `/predict`, so a fabricated series produced a fabricated live forecast.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(MandiPrice.arrival_date, MandiPrice.modal_price)
        .where(
            MandiPrice.market.ilike(f"%{market.strip()}%"),
            MandiPrice.commodity.ilike(f"%{commodity.strip()}%"),
            MandiPrice.arrival_date >= cutoff,
            MandiPrice.modal_price.isnot(None),
        )
        .order_by(MandiPrice.arrival_date.asc())
    )
    return [
        {"date": _date_of(r.arrival_date), "price": float(r.modal_price),
         "is_synthetic": False}
        for r in result.all()
    ]


def _watch_state(price: float | None, delta: float | None, days_old: int | None) -> str:
    if price is None:
        return "NO_DATA"
    if days_old is not None and days_old > settings.price_max_age_days:
        return "STALE"
    if delta is None:
        return "UNKNOWN"
    return "BULLISH" if delta > 0 else ("CRASH_RISK" if delta < 0 else "STABLE")


@router.get("/latest-watch")
async def latest_prices(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """
    Watchlist ticker: latest verified mandi price per crop.

    Two honesty rules encoded here:
      1. Nothing is returned for an absent crop except an explicit NO_DATA row —
         the previous `base_prices` dict invented rupee amounts for a market it
         had never queried.
      2. A day-on-day delta is only reported when both observations come from
         the SAME mandi. Comparing this week's Kolar price with last week's
         Hosakote price is a market comparison, not a price movement.
    """
    # Cotton and Sugarcane are excluded — traded on different exchanges and not
    # present in the Karnataka AGMARKNET dataset this system uses.
    top_crops = ["Tomato", "Onion", "Potato", "Ragi", "Maize", "Brinjal", "Marigold"]
    results = []

    for crop in top_crops:
        latest = (await db.execute(
            select(MandiPrice.modal_price, MandiPrice.market, MandiPrice.district,
                   MandiPrice.arrival_date)
            .where(MandiPrice.commodity.ilike(f"%{crop}%"),
                   MandiPrice.modal_price.isnot(None))
            .order_by(MandiPrice.arrival_date.desc())
            .limit(1)
        )).first()

        if latest is None or latest.modal_price is None:
            results.append({
                "crop": crop.upper(),
                "mandi": None,
                "price": None,
                "delta": None,
                "state": "NO_DATA",
                "as_of": None,
                "days_old": None,
                "stale": False,
                "is_synthetic": False,
                "note": "No mandi record for this crop in the database.",
            })
            continue

        days_old = price_service.record_age_days(latest.arrival_date)
        prior = (await db.execute(
            select(MandiPrice.modal_price)
            .where(
                MandiPrice.commodity.ilike(f"%{crop}%"),
                MandiPrice.market.ilike(latest.market),
                MandiPrice.modal_price.isnot(None),
                MandiPrice.arrival_date < latest.arrival_date,
            )
            .order_by(MandiPrice.arrival_date.desc())
            .limit(1)
        )).first()

        delta = (round(float(latest.modal_price) - float(prior.modal_price), 2)
                 if prior is not None and prior.modal_price is not None else None)

        results.append({
            "crop": crop.upper(),
            "mandi": latest.market,
            "district": latest.district,
            "price": float(latest.modal_price),
            "delta": delta,
            "state": _watch_state(float(latest.modal_price), delta, days_old),
            "as_of": _date_of(latest.arrival_date),
            "days_old": days_old,
            "stale": days_old is not None and days_old > settings.price_max_age_days,
            "is_synthetic": False,
            "note": (None if delta is not None
                     else "No earlier record from this same mandi, so no movement can be reported."),
        })

    return results


@router.get("/crops-markets")
async def get_crops_markets(db: AsyncSession = Depends(get_db)) -> dict:
    """Returns a list of all unique crops and markets in the MandiPrice database."""
    crops_result = await db.execute(select(MandiPrice.commodity).distinct().where(MandiPrice.commodity.isnot(None)))
    markets_result = await db.execute(select(MandiPrice.market).distinct().where(MandiPrice.market.isnot(None)))
    
    crops = [c[0].strip().title() for c in crops_result.all() if c[0]]
    markets = [m[0].strip().title() for m in markets_result.all() if m[0]]
    
    # Fallback to standard set if empty — option lists for the pickers, not
    # monetary values, so a static default here fabricates no market data.
    if not crops:
        crops = ["Tomato", "Potato", "Onion", "Maize", "Ragi", "Brinjal", "Marigold"]
    if not markets:
        markets = ["Kolar", "Belagavi", "Chikkaballapur", "Dharwad", "Mysuru"]
        
    return {
        "crops": sorted(list(set(crops))),
        "markets": sorted(list(set(markets)))
    }


@router.get("/districts")
async def get_districts(db: AsyncSession = Depends(get_db)) -> dict:
    """
    Returns canonical district names from the MandiPrice table.

    Distinct from /crops-markets which returns mandi names (MandiPrice.market).
    This endpoint returns MandiPrice.district — the administrative district field
    used for routing in message_handler.py and farmer_service.py.

    Used by the Telegram bot to populate district selection keyboards so that
    farmers select the correct district name for backend NLP + saturation queries.
    """
    result = await db.execute(
        select(MandiPrice.district).distinct().where(MandiPrice.district.isnot(None))
    )
    districts = [r[0].strip().title() for r in result.all() if r[0]]

    # Fallback: full 31-district canonical list so keyboards are never empty.
    if not districts:
        from backend.services.message_handler import CANONICAL_DISTRICTS
        districts = sorted(CANONICAL_DISTRICTS.values())

    return {"districts": sorted(list(set(districts)))}
