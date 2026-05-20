from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.models import MandiPrice

BASE_DIR   = Path(__file__).resolve().parents[2]
MODELS_DIR = BASE_DIR / "data" / "models"

MODEL: object | None = None
FEATURES: list[str] = []

_PRICE_PATTERNS: dict[str, dict[str, list[int]]] = {
    "Tomato": {
        "Kolar":           [1800,2200,2800,1200,900,1600,2100,2400,2000,1700,2500,2900],
        "Chikkaballapur":  [1700,2100,2700,1100,850,1500,2000,2300,1900,1600,2400,2800],
    },
    "Potato":   {"Kolar":          [1200,1100,1000,1300,1400,1500,1600,1400,1200,1100,1000,900]},
    "Onion":    {"Kolar":          [2000,1800,1600,1400,1200,1000,1200,1600,2000,2400,2800,2200]},
    "Marigold": {"Chikkaballapur": [800,900,1200,1800,2400,2000,1600,1200,900,800,900,1100]},
}


def load_model() -> None:
    global MODEL, FEATURES
    try:
        MODEL = joblib.load(MODELS_DIR / "price_model.pkl")
        with open(MODELS_DIR / "model_metadata.json") as f:
            FEATURES = json.load(f)["features"]
        print(f"[startup] Price model loaded — {len(FEATURES)} features.")
    except Exception as exc:
        print(f"[startup] Model not loaded: {exc}")


def generate_sample_history(market: str, commodity: str, days: int) -> list[dict]:
    patterns = _PRICE_PATTERNS.get(commodity, {}).get(
        market, _PRICE_PATTERNS["Tomato"]["Chikkaballapur"]
    )
    rng   = np.random.default_rng(42)
    today = date.today()
    return [
        {
            "date":  (today - timedelta(days=i)).isoformat(),
            "price": round(float(max(200, patterns[(today - timedelta(days=i)).month - 1]
                                    + rng.normal(0, patterns[(today - timedelta(days=i)).month - 1] * 0.08))), 0),
        }
        for i in range(days, 0, -1)
    ]


async def build_features(
    current_price: float,
    arrivals: float,
    month: int,
    commodity: str = "",
    market: str = "",
    db: AsyncSession | None = None,
) -> pd.DataFrame:
    prices_list: list[float] = []

    if db is not None and commodity and market:
        result = await db.execute(
            select(MandiPrice.modal_price)
            .where(
                MandiPrice.commodity.ilike(commodity),
                MandiPrice.market.ilike(market),
                MandiPrice.modal_price.isnot(None),
            )
            .order_by(MandiPrice.arrival_date.desc())
            .limit(30)
        )
        prices_list = [r for r in result.scalars().all()]

    if len(prices_list) >= 3:
        price_7d_avg   = float(np.mean(prices_list[:7]  if len(prices_list) >= 7  else prices_list))
        price_30d_avg  = float(np.mean(prices_list[:30] if len(prices_list) >= 10 else prices_list))
        price_7d_ago   = prices_list[6]  if len(prices_list) > 6  else prices_list[-1]
        price_30d_ago  = prices_list[29] if len(prices_list) > 29 else prices_list[-1]
        price_trend_7d = (current_price - price_7d_ago) / price_7d_ago if price_7d_ago else 0.03
        seasonal_avg   = float(np.mean(prices_list))
        vs_seasonal    = current_price / seasonal_avg if seasonal_avg else 1.0

        arr_result = await db.execute(
            select(MandiPrice.arrivals_tonnes)
            .where(
                MandiPrice.commodity.ilike(commodity),
                MandiPrice.market.ilike(market),
                MandiPrice.arrivals_tonnes.isnot(None),
            )
            .order_by(MandiPrice.arrival_date.desc())
            .limit(7)
        )
        arr_list        = [r for r in arr_result.scalars().all()]
        arrivals_7d_avg = float(np.mean(arr_list)) if arr_list else arrivals * 1.05
    else:
        price_7d_avg    = current_price * 0.97
        price_30d_avg   = current_price * 0.95
        price_7d_ago    = current_price * 0.96
        price_30d_ago   = current_price * 0.91
        price_trend_7d  = 0.03
        vs_seasonal     = 1.0
        seasonal_avg    = current_price * 0.95
        arrivals_7d_avg = arrivals * 1.05

    season = 0 if month in [6,7,8,9,10,11] else (1 if month in [12,1,2,3] else 2)
    values: dict[str, float] = {
        "month":           month,
        "month_sin":       float(np.sin(2 * np.pi * month / 12)),
        "month_cos":       float(np.cos(2 * np.pi * month / 12)),
        "season":          season,
        "quarter":         (month - 1) // 3 + 1,
        "modal_price":     current_price,
        "price_7d_avg":    price_7d_avg,
        "price_30d_avg":   price_30d_avg,
        "price_7d_ago":    price_7d_ago,
        "price_30d_ago":   price_30d_ago,
        "price_trend_7d":  price_trend_7d,
        "vs_seasonal":     vs_seasonal,
        "seasonal_avg":    seasonal_avg,
        "arrivals_tonnes": arrivals,
        "arrivals_7d_avg": arrivals_7d_avg,
    }
    row = {f: values.get(f, 0.0) for f in FEATURES}
    return pd.DataFrame([row])[FEATURES]

def price_signal(pred: float, current: float) -> tuple[str, str]:
    pct = (pred - current) / current * 100
    if pct > 10:
        return "WAIT — Price likely rising", "ಬೆಲೆ ಏರಲಿದೆ — ಕಾಯಿರಿ ⬆"
    if pct < -10:
        return "SELL NOW — Price likely falling", "ಈಗಲೇ ಮಾರಿ — ಬೆಲೆ ಇಳಿಯಲಿದೆ ⬇"
    return "NEUTRAL — Monitor weekly", "ಸ್ಥಿರ ಬೆಲೆ — ವಾರ ವಾರ ಗಮನಿಸಿ ➡"
