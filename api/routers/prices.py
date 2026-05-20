from datetime import date, datetime, timedelta
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.models import MandiPrice
from api.schemas import PriceRequest
from api.services import ml_service

router = APIRouter(prefix="/prices", tags=["prices"])

@router.post("/predict")
async def predict_price(
    req: PriceRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    if ml_service.MODEL is None:
        raise HTTPException(503, "Model not loaded. Run scripts/03_train_model.py first.")

    X    = await ml_service.build_features(
        req.current_price, req.arrivals_tonnes or 100.0,
        date.today().month, req.commodity, req.market, db,
    )
    pred  = float(ml_service.MODEL.predict(X)[0])
    trees = np.array([t.predict(X)[0] for t in ml_service.MODEL.estimators_])
    low, high = float(np.percentile(trees, 15)), float(np.percentile(trees, 85))
    signal, signal_kn = ml_service.price_signal(pred, req.current_price)

    return {
        "commodity":       req.commodity,
        "market":          req.market,
        "current_price":   req.current_price,
        "predicted_price": round(pred, 0),
        "confidence_low":  round(low, 0),
        "confidence_high": round(high, 0),
        "signal":          signal,
        "signal_kannada":  signal_kn,
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
        return [{"date": r.arrival_date.date().isoformat(), "price": r.modal_price} for r in rows]
    return ml_service.generate_sample_history(market, commodity, days)
