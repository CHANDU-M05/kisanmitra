from datetime import date, datetime, timedelta
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.models import MandiPrice
from backend.schemas import PriceRequest
from backend.services import ml_service

router = APIRouter(prefix="/prices", tags=["prices"])

@router.get("/predict")
async def predict_price(
    commodity: str = Query(...),
    market: str = Query(...),
    current_price: float = Query(...),
    arrivals_tonnes: float = Query(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if ml_service.MODEL is None:
        raise HTTPException(503, "Model not loaded. Run scripts/03_train_model.py first.")

    # If caller didn't supply arrivals_tonnes, pull the latest real value from DB.
    if arrivals_tonnes is None:
        arr_row = await db.execute(
            select(MandiPrice.arrivals_tonnes)
            .where(
                MandiPrice.commodity.ilike(commodity),
                MandiPrice.market.ilike(market),
                MandiPrice.arrivals_tonnes.isnot(None),
            )
            .order_by(MandiPrice.arrival_date.desc())
            .limit(1)
        )
        latest_arr = arr_row.scalar_one_or_none()
        arrivals_tonnes = float(latest_arr) if latest_arr else 100.0

    X    = await ml_service.build_features(
        current_price, arrivals_tonnes,
        date.today().month, commodity, market, db,
    )
    pred_res = ml_service.make_prediction(X, current_price)
    pred = pred_res["pred"]
    low = pred_res["low"]
    high = pred_res["high"]
    signal, signal_kn = ml_service.price_signal(pred, current_price)

    meta = ml_service.crop_prediction_meta(commodity, current_price)

    # Anomaly calculation (>30% shift vs current spot price)
    price_diff_pct = abs(pred - current_price) / max(current_price, 1) * 100
    is_anomaly = price_diff_pct > 30.0
    anomaly_type = "SPIKE" if pred > current_price else ("CRASH" if pred < current_price else "NORMAL")

    return {
        "commodity":       commodity,
        "market":          market,
        "current_price":   current_price,
        "predicted_price": round(pred, 0),
        "confidence_low":  round(low, 0),
        "confidence_high": round(high, 0),
        "signal":          signal,
        "signal_kannada":  signal_kn,
        "is_anomaly":      is_anomaly,
        "anomaly_type":    anomaly_type,
        "deviation_pct":   round(price_diff_pct, 1),
        # Per-crop model accuracy and MSP — served from backend lookup tables
        # so the frontend never holds a stale hardcoded figure.
        "crop_mape_pct":   meta["crop_mape_pct"],   # float | null
        "msp_floor":       meta["msp_floor"],        # float | null (null = non-MSP crop)
        "msp_ratio":       meta["msp_ratio"],        # float | null
    }


@router.get("/history/{market}/{commodity}")
async def price_history(
    market: str,
    commodity: str,
    days: int = Query(default=60, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    cutoff = datetime.now() - timedelta(days=days)
    result = await db.execute(
        select(MandiPrice.arrival_date, MandiPrice.modal_price)
        .where(
            MandiPrice.market.ilike(market),
            MandiPrice.commodity.ilike(commodity),
            MandiPrice.arrival_date >= cutoff,
        )
        .order_by(MandiPrice.arrival_date.asc())
    )
    rows = result.all()
    if rows:
        return [{"date": r.arrival_date.date().isoformat(), "price": r.modal_price, "is_synthetic": False} for r in rows]
    
    synthetic_data = ml_service.generate_sample_history(market, commodity, days)
    for item in synthetic_data:
        item["is_synthetic"] = True
    return synthetic_data

@router.get("/latest-watch")
async def latest_prices(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Returns the latest spot prices for top commodities for the UI watchlist.
    
    Delta is calculated as the difference between the two most recent modal prices
    per commodity, so it reflects an actual price movement rather than a random stub.
    """
    # Only include crops that have real data in the AGMARKNET database.
    # Cotton and Sugarcane are excluded — they are traded on different exchanges
    # and are not present in the Karnataka AGMARKNET dataset used by this system.
    top_crops = ["Tomato", "Onion", "Potato", "Ragi", "Maize", "Brinjal", "Marigold"]
    results = []

    for crop in top_crops:
        res = await db.execute(
            select(MandiPrice.modal_price, MandiPrice.district, MandiPrice.arrival_date)
            .where(MandiPrice.commodity.ilike(crop), MandiPrice.modal_price.isnot(None))
            .order_by(MandiPrice.arrival_date.desc())
            .limit(2)
        )
        rows = res.all()
        if rows:
            latest_price = rows[0].modal_price
            prev_price = rows[1].modal_price if len(rows) > 1 else latest_price
            delta = round(latest_price - prev_price, 2)
            results.append({
                "crop": crop.upper(),
                "mandi": f"{rows[0].district} Mandi",
                "price": latest_price,
                "delta": delta,
                "state": "BULLISH" if delta > 0 else ("CRASH_RISK" if delta < 0 else "STABLE"),
                "is_synthetic": False,
            })
        else:
            # Fallback for empty DB — realistic reference prices from Karnataka mandis
            base_prices = {
                "Tomato": 1720, "Onion": 1580, "Potato": 2100,
                "Ragi": 3850, "Maize": 2100, "Brinjal": 1200, "Marigold": 900,
            }
            results.append({
                "crop": crop.upper(),
                "mandi": "Karnataka Mandi",
                "price": base_prices.get(crop, 2000),
                "delta": 0.0,
                "state": "STABLE",
                "is_synthetic": True,
            })

    return results


@router.get("/crops-markets")
async def get_crops_markets(db: AsyncSession = Depends(get_db)) -> dict:
    """Returns a list of all unique crops and markets in the MandiPrice database."""
    crops_result = await db.execute(select(MandiPrice.commodity).distinct().where(MandiPrice.commodity.isnot(None)))
    markets_result = await db.execute(select(MandiPrice.market).distinct().where(MandiPrice.market.isnot(None)))
    
    crops = [c[0].strip().title() for c in crops_result.all() if c[0]]
    markets = [m[0].strip().title() for m in markets_result.all() if m[0]]
    
    # Fallback to standard set if empty
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
