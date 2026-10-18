from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.models import MandiPrice

import logging
logger = logging.getLogger("kisanmitra.ml_service")

BASE_DIR   = Path(__file__).resolve().parents[2]
# Production containers get the models via a read-only bind mount and set
# MODEL_DIR; the repo path keeps local development working unchanged.
MODELS_DIR = Path(settings.model_dir) if settings.model_dir else BASE_DIR / "data" / "models"

MODEL: object | None = None
ENCODERS: dict | None = None
FEATURES: list[str] = []
METADATA: dict = {}

# ── Per-crop MAPE from the clean chronological benchmark (task-4052 / task-4119)
# Source: scripts/clean_benchmark.py — chronological 80/20 split, 9,672 rows,
# January 2020 → April 2025. Update this table whenever the model is retrained
# and the benchmark is re-run, so the frontend always reflects the live model's
# true accuracy rather than drifting from a hardcoded stale figure.
CROP_MAPE: dict[str, float] = {
    "Maize":    8.61,
    "Ragi":     8.54,
    "Brinjal":  15.50,
    "Potato":   16.09,
    "Tomato":   27.84,
    "Onion":    28.68,
    "Marigold": 30.65,
}

# ── Official MSP (Rs/quintal) currently in effect — 2025-26 Kharif season
# Source: CCEA cabinet announcement, pib.gov.in press release (June 2025)
# Only Maize and Ragi carry an official MSP; all other crops in this study
# are perishable vegetables/flowers outside India's MSP scheme (None = N/A).
MSP_CURRENT: dict[str, float | None] = {
    "Maize":    2400.0,   # 2025-26 Kharif MSP
    "Ragi":     4886.0,   # 2025-26 Kharif MSP
    "Brinjal":  None,
    "Potato":   None,
    "Tomato":   None,
    "Onion":    None,
    "Marigold": None,
}

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
    global MODEL, ENCODERS, FEATURES, METADATA, CROP_MAPE, MSP_CURRENT
    try:
        MODEL = joblib.load(MODELS_DIR / "price_model.pkl")
        ENCODERS = joblib.load(MODELS_DIR / "encoders.pkl")
        with open(MODELS_DIR / "model_metadata.json") as f:
            METADATA = json.load(f)
            FEATURES = METADATA.get("features", [])
            if "crop_median_mape" in METADATA:
                CROP_MAPE = METADATA["crop_median_mape"]
            elif "crop_mape" in METADATA:
                CROP_MAPE = METADATA["crop_mape"]
            if "crop_msp" in METADATA:
                MSP_CURRENT = METADATA["crop_msp"]
        
        # Verify shape alignment at boot
        if MODEL is not None:
            expected_count = MODEL.n_features_in_
            if len(FEATURES) != expected_count:
                raise RuntimeError(
                    f"Feature mismatch: metadata features list has {len(FEATURES)} columns, "
                    f"but the loaded model expects {expected_count} columns."
                )
        logger.info(f"[startup] Price model loaded — {len(FEATURES)} features.")
    except Exception as exc:
        logger.error(f"[startup] Model not loaded: {exc}")
        raise exc


def generate_sample_history(market: str, commodity: str, days: int) -> list[dict]:
    commodity_patterns = _PRICE_PATTERNS.get(commodity, {})
    patterns = commodity_patterns.get(market)
    if patterns is None:
        _fallback_commodity = "Tomato"
        _fallback_market    = "Chikkaballapur"
        logger.warning(
            "[SYNTHETIC HISTORY] No price patterns for commodity=%r market=%r — "
            "falling back to %s/%s patterns. Data is synthetic and may not reflect "
            "real price levels for this crop/region.",
            commodity, market, _fallback_commodity, _fallback_market,
        )
        patterns = _PRICE_PATTERNS[_fallback_commodity][_fallback_market]

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


def get_season_label(month: int) -> str:
    """Map month (1-12) to season label matching training time encoder."""
    if month in (12, 1, 2):
        return "Winter"
    elif month in (3, 4, 5):
        return "Summer"
    elif month in (6, 7, 8, 9):
        return "Monsoon"
    else:
        return "Post-Monsoon"


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
        # Calculate clean prior-years seasonal average matching the training feature
        prior_prices = []
        if db is not None:
            from datetime import date
            current_year = date.today().year
            hist_result = await db.execute(
                select(MandiPrice.arrival_date, MandiPrice.modal_price)
                .where(
                    MandiPrice.commodity.ilike(commodity),
                    MandiPrice.market.ilike(market),
                    MandiPrice.modal_price.isnot(None),
                )
            )
            hist_rows = hist_result.all()
            prior_prices = [
                r.modal_price for r in hist_rows
                if r.arrival_date.month == month and r.arrival_date.year < current_year
            ]
        
        seasonal_avg = float(np.mean(prior_prices)) if prior_prices else price_30d_avg
        vs_seasonal  = current_price / seasonal_avg if seasonal_avg else 1.0

        # New features computed from DB history
        price_momentum_7d    = (current_price - price_7d_ago) / price_7d_ago if price_7d_ago else 0.0
        price_volatility_30d = float(np.std(prices_list)) if len(prices_list) >= 5 else 0.0

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
        price_7d_avg         = current_price * 0.97
        price_30d_avg        = current_price * 0.95
        price_7d_ago         = current_price * 0.96
        price_30d_ago        = current_price * 0.91
        price_trend_7d       = 0.03
        vs_seasonal          = 1.0
        seasonal_avg         = current_price * 0.95
        arrivals_7d_avg      = arrivals * 1.05
        price_momentum_7d    = 0.03
        price_volatility_30d = 0.0

    season_label = get_season_label(month)
    season_encoded = 0.0
    if ENCODERS and "season" in ENCODERS and hasattr(ENCODERS["season"], "classes_"):
        if season_label in ENCODERS["season"].classes_:
            season_encoded = float(ENCODERS["season"].transform([season_label])[0])

    days_since_last_report = 0.0
    if db is not None and commodity and market:
        last_date_res = await db.execute(
            select(MandiPrice.arrival_date)
            .where(
                MandiPrice.commodity.ilike(commodity),
                MandiPrice.market.ilike(market),
            )
            .order_by(MandiPrice.arrival_date.desc())
            .limit(1)
        )
        last_date = last_date_res.scalar_one_or_none()
        if last_date:
            # NOTE: datetime is a subclass of date, so isinstance(x, date) alone
            # cannot tell a TIMESTAMP column (which SQLAlchemy returns as a
            # tz-aware datetime) from a DATE column. Normalise first, subtract
            # dates only — the previous ordering raised TypeError on live data.
            last_day = last_date.date() if isinstance(last_date, datetime) else last_date
            days_since_last_report = float((date.today() - last_day).days)
    
    commodity_encoded = 0.0
    market_encoded = 0.0
    if ENCODERS:
        try:
            if "commodity" in ENCODERS and commodity in ENCODERS["commodity"].classes_:
                commodity_encoded = float(ENCODERS["commodity"].transform([commodity])[0])
            if "market" in ENCODERS and market in ENCODERS["market"].classes_:
                market_encoded = float(ENCODERS["market"].transform([market])[0])
        except Exception:
            pass

    values: dict[str, float] = {
        "commodity_encoded": commodity_encoded,
        "market_encoded":  market_encoded,
        "month":           float(month),
        "month_sin":       float(np.sin(2 * np.pi * month / 12)),
        "month_cos":       float(np.cos(2 * np.pi * month / 12)),
        "season_encoded":  season_encoded,
        "season":          season_encoded,
        "quarter":         float((month - 1) // 3 + 1),
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
        "price_momentum_7d": price_momentum_7d,
        "price_volatility_30d": price_volatility_30d,
        "days_since_last_report": days_since_last_report,
    }
    row = {f: values.get(f, 0.0) for f in FEATURES}
    return pd.DataFrame([row])[FEATURES]

def price_signal(pred: float, current: float, commodity: str | None = None) -> tuple[str, str]:
    """Actionable SELL/WAIT signal ONLY when the forecast movement clears
    half of the crop's own benchmark MAPE. For high-MAPE crops (Tomato ~28%)
    a ±10% 'signal' is statistical noise — the band widens so the bot stays
    NEUTRAL instead of issuing confident wrong advice.
    """
    pct = (pred - current) / current * 100
    mape = CROP_MAPE.get((commodity or "").strip().title())
    band = max(10.0, (mape / 2.0) if mape else 0.0)
    if pct > band:
        return "WAIT — Price likely rising", "ಬೆಲೆ ಏರಲಿದೆ — ಕಾಯಿರಿ ⬆"
    if pct < -band:
        return "SELL NOW — Price likely falling", "ಈಗಲೇ ಮಾರಿ — ಬೆಲೆ ಇಳಿಯಲಿದೆ ⬇"
    return "NEUTRAL — Monitor weekly", "ಸ್ಥಿರ ಬೆಲೆ — ವಾರ ವಾರ ಗಮನಿಸಿ ➡"


def crop_prediction_meta(commodity: str, current_price: float) -> dict:
    """Return per-crop model accuracy and MSP metadata for the predict response.

    Both figures are sourced from this module's lookup tables (CROP_MAPE,
    MSP_CURRENT) so the frontend always reflects the current model's stats
    rather than a hardcoded stale figure in client-side code.
    """
    # Normalise casing for lookup — tolerate 'tomato', 'TOMATO', 'Tomato'
    key = commodity.strip().title()
    mape  = CROP_MAPE.get(key)          # None if crop not in benchmark table
    floor = MSP_CURRENT.get(key)        # None for non-MSP crops

    return {
        "crop_mape_pct": mape,          # float | None
        "msp_floor":     floor,         # float | None — official MSP in Rs/quintal
        "msp_ratio":     round(current_price / floor, 3) if floor else None,
    }


def make_prediction(X: np.ndarray, current_price: float, commodity: str | None = None) -> dict[str, float]:
    """
    Safely make a price prediction using MODEL and METADATA.
    Handles log1p target inverse transformation (np.expm1) if specified in metadata.
    Enforces a 5x sanity bound relative to current_price.
    Returns: {"pred": float, "low": float, "high": float}
    """
    if MODEL is None:
        raise RuntimeError("Model is not loaded.")

    algorithm_str = str(METADATA.get("algorithm", "")).lower()
    notes_str = str(METADATA.get("notes", "")).lower()
    is_log = "log1p" in algorithm_str or "log1p" in notes_str

    raw_pred = float(MODEL.predict(X)[0])
    pred = float(np.expm1(raw_pred)) if is_log else raw_pred

    if hasattr(MODEL, "estimators_"):
        import warnings as _warnings
        with _warnings.catch_warnings():
            _warnings.simplefilter("ignore", UserWarning)
            raw_trees = np.array([t.predict(X)[0] for t in MODEL.estimators_])
        trees = np.expm1(raw_trees) if is_log else raw_trees
        low = float(np.percentile(trees, 15))
        high = float(np.percentile(trees, 85))
    else:
        # No tree ensemble to sample: use the crop's own benchmark MAPE as an
        # honest uncertainty band instead of a fake ±15% precision claim.
        mape = CROP_MAPE.get((commodity or "").strip().title())
        band = min(0.35, max(0.15, (mape / 100.0) if mape else 0.15))
        low = pred * (1 - band)
        high = pred * (1 + band)

    # Sanity guard: prediction must not deviate by >5x or <1/5th from current_price
    if current_price > 0:
        ratio = pred / current_price
        if ratio < 0.2 or ratio > 5.0:
            logger.error(
                "[SANITY GUARD FAILED] Predicted price ₹%.2f is outside 5x bound of current price ₹%.2f (ratio=%.2f)",
                pred, current_price, ratio
            )
            raise ValueError(
                f"Prediction ₹{pred:.0f} failed sanity check relative to spot price ₹{current_price:.0f}."
            )

    return {
        "pred": pred,
        "low": low,
        "high": high,
    }

