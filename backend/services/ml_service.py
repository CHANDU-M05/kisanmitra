from __future__ import annotations

import json
import math
import re
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

# Model readiness is surfaced separately from MODEL so /health and /predict can
# tell "still loading" (a transient cold-start state worth retrying) apart from
# "not available" (a missing/failed artifact). One of: unloaded, loading, ready,
# failed.
MODEL_STATUS: str = "unloaded"
MODEL_STATUS_DETAIL: str = "model load has not started"

# Provenance of the artifact actually loaded into memory and whether the shipped
# metadata describes it. Surfaced on /health so a metadata/model drift — e.g.
# CatBoost metrics published alongside a RandomForest artifact — is visible to an
# operator instead of silently driving the accuracy the frontend displays.
SERVED_MODEL_PROVENANCE: dict = {}
MODEL_METADATA_MATCHES: bool | None = None

_MODEL_FILES = ("price_model.pkl", "encoders.pkl", "model_metadata.json")


def model_loaded() -> bool:
    return MODEL is not None and MODEL_STATUS == "ready"


def unavailable_detail() -> str:
    """Explain why a forecast is not possible right now.

    A cold start that is still loading is a retry-later situation, not a
    broken deployment; only report the training hint once loading has failed.
    """
    if MODEL_STATUS == "loading":
        return "Model is still loading after a cold start; retry in a few seconds."
    return "Model not loaded. Run scripts/03_train_model.py first."


def models_present() -> bool:
    """True when every required artifact already exists in MODEL_DIR."""
    return all((MODELS_DIR / name).is_file() for name in _MODEL_FILES)


def _download_and_verify_models() -> None:
    """
    Fetch MODEL_URL into MODEL_DIR only after its SHA-256 matches MODEL_SHA256.

    A pickle executes arbitrary code on load, so an unverified download is never
    run: a missing or mismatching digest raises before anything is unpickled.
    The archive is a gzipped tar holding the three files at its root (the format
    produced by publishing data/models as a GitHub Release asset).
    """
    import hashlib
    import tarfile
    import tempfile
    import urllib.request

    url = settings.model_url
    expected = (settings.model_sha256 or "").strip().lower()
    if not url:
        raise RuntimeError(
            "Model artifacts are absent from MODEL_DIR and MODEL_URL is not set. "
            "Mount the models or provide MODEL_URL + MODEL_SHA256."
        )
    if not expected:
        raise RuntimeError(
            "MODEL_URL is set but MODEL_SHA256 is not; refusing to download and "
            "un-pickle an unverified model archive."
        )

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        with urllib.request.urlopen(url, timeout=120) as resp:  # noqa: S310 (operator-set URL)
            digest = hashlib.sha256()
            with open(tmp_path, "wb") as fh:
                while chunk := resp.read(1 << 20):
                    digest.update(chunk)
                    fh.write(chunk)
        actual = digest.hexdigest()
        if actual != expected:
            raise RuntimeError(
                f"Model archive SHA-256 mismatch (expected {expected}, got {actual}); "
                "refusing to load an unverified model."
            )
        with tarfile.open(tmp_path, "r:*") as tar:
            # Reject absolute paths / traversal before extracting.
            for member in tar.getmembers():
                if member.name.startswith("/") or ".." in Path(member.name).parts:
                    raise RuntimeError(f"Unsafe path in model archive: {member.name}")
            tar.extractall(MODELS_DIR)
    finally:
        tmp_path.unlink(missing_ok=True)
    if not models_present():
        raise RuntimeError(
            "Model archive verified and extracted but the expected files are still "
            f"missing from {MODELS_DIR}."
        )


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
    global MODEL_STATUS, MODEL_STATUS_DETAIL
    global MODEL_METADATA_MATCHES, SERVED_MODEL_PROVENANCE
    MODEL_STATUS = "loading"
    MODEL_STATUS_DETAIL = "loading model artifacts"
    try:
        if not models_present():
            _download_and_verify_models()
        MODEL = joblib.load(MODELS_DIR / "price_model.pkl")
        ENCODERS = joblib.load(MODELS_DIR / "encoders.pkl")
        with open(MODELS_DIR / "model_metadata.json") as f:
            METADATA = json.load(f)
            FEATURES = METADATA.get("features", [])

            # Reconcile the published metadata with the artifact actually loaded.
            # The frontend's crop MAPE/uncertainty are derived from this table, so
            # it must describe the serving model — never a different one.
            served_algorithm = type(MODEL).__name__ if MODEL is not None else ""
            meta_algorithm = str(METADATA.get("algorithm", "")) or ""
            if meta_algorithm and served_algorithm:
                MODEL_METADATA_MATCHES = meta_algorithm == served_algorithm
                if not MODEL_METADATA_MATCHES:
                    logger.warning(
                        "model_metadata.json algorithm=%r does not match the loaded "
                        "artifact %r; keeping the artifact-consistent CROP_MAPE so the "
                        "displayed accuracy always describes the serving model.",
                        meta_algorithm, served_algorithm,
                    )
            else:
                MODEL_METADATA_MATCHES = None
            try:
                import sklearn as _sk
                sklearn_runtime = _sk.__version__
            except Exception:
                sklearn_runtime = "unknown"
            SERVED_MODEL_PROVENANCE = {
                "algorithm": served_algorithm,
                "n_features": int(getattr(MODEL, "n_features_in_", 0) or 0),
                "metadata_algorithm": meta_algorithm,
                "metadata_matches": MODEL_METADATA_MATCHES,
                "sklearn_runtime": sklearn_runtime,
                # The coverage the model can actually answer for, surfaced on
                # /health: a 6x40 vocabulary serving 11x152 live categories is
                # the reason most pairs must report unavailable rather than a
                # number, and an operator reading only the logs would never see it.
                "trained_commodities": vocab_size("commodity"),
                "trained_markets": vocab_size("market"),
            }

            # Adopt metadata accuracy only when it describes the served model
            # (matches or the doc simply omits `algorithm`); a mismatched doc must
            # never relabel the running model's real error.
            if MODEL_METADATA_MATCHES is not False:
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
        MODEL_STATUS = "ready"
        MODEL_STATUS_DETAIL = f"loaded {len(FEATURES)} features"
    except Exception as exc:
        logger.error(f"[startup] Model not loaded: {exc}")
        MODEL = None
        MODEL_STATUS = "failed"
        MODEL_STATUS_DETAIL = str(exc)
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


# ── Encoder vocabulary reconciliation ────────────────────────────────────────
# The fitted encoders know 6 commodities and 40 bare mandi names, while live
# AGMARKNET rows carry 11 commodities and 152 markets suffixed with "APMC"/
# "Apmc". A label encoder has no unseen-category handling, so a miss used to
# fall through to 0.0 — which is indistinguishable from the *legitimate* code
# for the first sorted class ("Brinjal" / "Arasikere"). Every mismatching
# forecast was therefore silently scored as "crop #0 at market #0", an
# out-of-range blend of the whole training set, and published with full
# confidence. These helpers resolve a live name to a real fitted class and
# report a miss as a miss so the caller can refuse to forecast.
#
# Normalisation only reconciles *presentation* (suffix, case, punctuation). It
# never invents a class: if the normalised name is not a fitted class, that
# commodity/market was not in training and no number is defensible.
_MARKET_SUFFIXES = ("apmc market committee", "apmc", "amc", "market yard",
                    "yard", "market", "mandy")
# Verified spellings only: live data publishes both "Ragi" and the trained
# "Ragi (Finger Millet)"; both denote the same fitted class. Nothing is aliased
# that is not confirmed present in classes_ (see encoder_coverage).
_COMMODITY_ALIASES = {
    "ragi": "Ragi (Finger Millet)",
    "finger millet": "Ragi (Finger Millet)",
    "ragi finger millet": "Ragi (Finger Millet)",
}


def _canonical(name: str | None) -> str:
    """Lowercase, drop punctuation, and strip a trailing mandi suffix."""
    text = re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()
    changed = True
    while changed:
        changed = False
        for suffix in _MARKET_SUFFIXES:
            if text.endswith(" " + suffix):
                text = text[: -len(suffix)].strip()
                changed = True
    return text


_VOCAB_CACHE: dict[str, dict[str, str]] = {}


def _vocab(axis: str) -> dict[str, str]:
    """canonical form -> exact fitted class label, for one encoder axis."""
    if ENCODERS is None or axis not in ENCODERS:
        return {}
    key = f"{id(ENCODERS[axis])}:{axis}"
    if key not in _VOCAB_CACHE:
        classes = getattr(ENCODERS[axis], "classes_", None)
        # classes_ is a numpy array: `array or []` raises on the ambiguous truth
        # value, so test for None explicitly.
        if classes is None:
            _VOCAB_CACHE[key] = {}
        else:
            _VOCAB_CACHE[key] = {_canonical(str(c)): str(c) for c in classes}
    return _VOCAB_CACHE[key]


def resolve_class(axis: str, value: str | None) -> str | None:
    """The exact fitted class label `value` denotes, or None when untrained."""
    if ENCODERS is None or axis not in ENCODERS:
        return None
    canonical = _canonical(value)
    if not canonical:
        return None
    classes = _vocab(axis)
    if canonical in classes:
        return classes[canonical]
    if axis == "commodity":
        aliased = _COMMODITY_ALIASES.get(canonical)
        if aliased and _canonical(aliased) in classes:
            return classes[_canonical(aliased)]
    return None


def encoder_coverage(commodity: str, market: str) -> dict:
    """Whether both categorical axes exist in the trained vocabulary.

    Returns the resolved class labels plus the list of axes that are missing,
    so an unavailable forecast can name the specific gap instead of emitting a
    plausible-looking number. A missing axis is not a data-quality note: the
    model cannot score a category it never saw.
    """
    commodity_class = resolve_class("commodity", commodity)
    market_class = resolve_class("market", market)
    missing = [name for name, cls in (("commodity", commodity_class),
                                      ("market", market_class)) if cls is None]
    encoders_available = ENCODERS is not None
    return {
        "commodity_class": commodity_class,
        "market_class": market_class,
        "missing": missing,
        # When no encoders are loaded the caller cannot tell a genuine miss from
        # an uninitialised artifact; readiness is already gated upstream, so do
        # not claim a vocabulary verdict here.
        "checked": encoders_available,
        "supported": encoders_available and not missing,
    }


def vocab_size(axis: str) -> int:
    """Number of fitted classes on one categorical axis (0 when unloaded)."""
    return len(_vocab(axis))


def supported_classes(axis: str) -> list[str]:
    """The exact class labels the model can score on one axis, sorted."""
    return sorted(_vocab(axis).values())


def encode_categorical(axis: str, value: str, fallback: float = 0.0) -> float:
    """Fitted encoder code for `value`, resolved through the normalised vocab.

    `fallback` exists only for the no-ENCODERS unit-test path; the live pipeline
    is gated by encoder_coverage before it can reach here.
    """
    resolved = resolve_class(axis, value)
    if resolved is None:
        return fallback
    try:
        return float(ENCODERS[axis].transform([resolved])[0])
    except Exception:  # noqa: BLE001 - label vanished between check and use
        return fallback


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
            # `date` is imported at module level; a local `from datetime import
            # date` here would make it function-local and raise UnboundLocalError
            # at the days_since_last_report computation whenever this branch did
            # not run (fewer than 3 stored prices — a freshly seeded database).
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
        # Resolved through the normalised vocabulary so a live "Ramanagara APMC"
        # reaches the fitted class "Ramanagara". A genuine miss stays a miss:
        # the 0.0 below is only reachable when the caller has not gated on
        # encoder_coverage, and price_service always does.
        commodity_encoded = encode_categorical("commodity", commodity)
        market_encoded = encode_categorical("market", market)
        missed = [axis for axis, value in (("commodity", commodity), ("market", market))
                  if resolve_class(axis, value) is None]
        if missed:
            logger.warning(
                "Encoding fell back to the default code for %s (%s): not in the "
                "trained vocabulary. Forecasts for this pair are not defensible.",
                missed, f"{commodity}@{market}",
            )

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


# ── Anomaly gate ─────────────────────────────────────────────────────────────
ANOMALY_MIN_THRESHOLD_PCT = 30.0   # legacy fixed floor — never more permissive
ANOMALY_MAPE_MULTIPLIER = 1.5      # deviation must clear 1.5x the crop's own MAPE


def anomaly_threshold_pct(commodity: str | None, crop_mape: float | None = None) -> float:
    """Deviation (in %) above which a forecast is labelled an anomaly.

    A fixed 30% gate mislabels the model's own noise on volatile crops: Tomato
    and Marigold carry benchmark MAPEs of ~28-31%, so any forecast movement of
    ~30% is within the model's known error range, not evidence of a market
    SPIKE/CRASH. The gate therefore scales with the crop's own error
    (1.5x MAPE, floored at the historical 30%) so the flag means "beyond what
    the model can explain" — and the effective threshold travels with the
    response so every channel can disclose it. This reclassifies the label
    only; it never suppresses the CI, the MAPE, or the estimate-not-guarantee
    disclaimer.
    """
    mape = crop_mape if crop_mape is not None else CROP_MAPE.get((commodity or "").strip().title())
    # A non-finite or non-numeric MAPE must not become a non-finite gate: that
    # would silently switch anomaly detection off (any comparison with NaN is
    # False) and leak an invalid NaN literal into the JSON response. Degrade to
    # the historical 30% floor instead.
    if not isinstance(mape, (int, float)) or isinstance(mape, bool) or not math.isfinite(mape) or mape <= 0:
        return ANOMALY_MIN_THRESHOLD_PCT
    return max(ANOMALY_MIN_THRESHOLD_PCT, mape * ANOMALY_MAPE_MULTIPLIER)


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

