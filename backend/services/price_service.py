"""Shared price-query and forecast service used by every channel.

Single source of truth for mandi price resolution: Telegram, WhatsApp and the
REST conversation endpoint all forecast through this function, so a price that
is real, fresh and market-consistent is a guarantee of every channel — not of
one channel that happens to share code with the others.

Three integrity rules enforced here:
  1. NEVER invent a spot price. No mandi row → ``no_data``.
  2. NEVER present an old price as today's. Beyond the freshness SLA → ``stale_data``.
  3. Every input the model received that had to be substituted is reported in
     ``data_quality``, so downstream formatters can tell the farmer the answer
     is degraded rather than silently smoothing it over.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.models import MandiPrice
from backend.services import data_refresh, ml_service

# ── Forecast calibration ─────────────────────────────────────────────────────
# The RandomForest learned next-day change RATES from a 2023-24 sample and its
# walk-forward accuracy is 9.2% MAE (model_metadata.json, mae_pct). Applied to a
# 2026 price level of 3000-5000 INR/qtl that rate gives a near-flat estimate,
# while a seasonal-peak crop's own history spans ±2000 INR — so the raw point
# estimate lands far outside the market's observed range yet is only ~3% away
# from the spot price. A band expressed in percent of the spot would therefore
# never fire, and a band expressed in absolute INR would reject every honest
# prediction for high-value vegetables.
#
# The defensible envelope below takes the wider of two views: half the crop's
# own observed spread at this mandi, or twice the model's published MAE applied
# to that crop's average price. The first keeps a wide-range crop from being
# judged by a tight absolute band; the second ties the gate to measured error
# rather than to a preference. The existing 5x sanity guard in ml_service stays
# as the outermost bound and is unaffected.
_FORECAST_BAND_MIN_PCT_OF_SPREAD = 0.5
_FORECAST_BAND_MIN_MAE_MULTIPLE = 2.0

_DISTRICT_ALIASES: dict[str, list[str]] = {
    "Tumakuru": ["Tumkur", "Tumakuru"],
    "Shivamogga": ["Shimoga", "Shivamogga"],
    "Bengaluru Urban": ["Bangalore", "Bengaluru"],
    "Bengaluru Rural": ["Bangalore", "Bengaluru"],
    "Belagavi": ["Belgaum", "Belagavi"],
    "Mysuru": ["Mysore", "Mysuru"],
    "Ballari": ["Bellary", "Ballari"],
    "Vijayapura": ["Bijapur", "Vijayapura"],
    "Kalaburagi": ["Gulbarga", "Kalaburagi"],
}

# Arrivals are reported, never invented. When a mandi has no recorded tonnage we
# pass 0.0 to the feature builder and flag `arrivals_unknown` — the deployed
# model's feature list (data/models/model_metadata.json) does not contain
# arrivals at all, so a fabricated tonnage would be pure theatre: it cannot
# change the forecast, but it can change what a reader believes about the market.
_ARRIVALS_UNKNOWN = 0.0


def _as_of_date(as_of_raw) -> date | None:
    """Normalise an arrival_date that may be a date, datetime or string."""
    if as_of_raw is None:
        return None
    if isinstance(as_of_raw, datetime):
        return as_of_raw.date()
    if isinstance(as_of_raw, date):
        return as_of_raw
    text = str(as_of_raw)[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _age_in_days(as_of_raw, today: date | None = None) -> int | None:
    """Days between the record's market date and today. None = unknown age.

    ``today`` defaults to the market calendar (IST), because AGMARKNET stamps
    arrival dates in IST: measuring them with a UTC-host clock makes a fresh
    row report a negative age for a few hours every evening, and the same
    frame must be used by the SLA gate and by `data_refresh`'s future-reject.
    """
    d = _as_of_date(as_of_raw)
    if d is None:
        return None
    return (today or data_refresh.market_today()).toordinal() - d.toordinal()


def record_age_days(as_of_raw, today: date | None = None) -> int | None:
    """Public alias: routers must not reach into `_age_in_days`."""
    return _age_in_days(as_of_raw, today)


async def _feed_newest_date(db: AsyncSession) -> date | None:
    """
    Newest market date anywhere in the feed.

    Needed to answer the question a stale refusal actually raises: is THIS crop
    missing recent data, or has nothing been published at all? The first is a
    coverage gap, the second is an upstream outage — and they deserve different
    sentences.
    """
    newest = (await db.execute(
        select(func.max(MandiPrice.arrival_date))
    )).scalar_one_or_none()
    return _as_of_date(newest)


async def _freshness_refusal(
    db: AsyncSession, *,
    region: dict[str, str],
    row,
    current_price: float,
    price_as_of: str,
    age_days: int | None,
    data_source: str,
    data_quality: list[str],
) -> dict:
    """
    The single stale-data refusal every forecast surface must return.

    Kept in one place because a second implementation is how `/prices/predict`
    ended up gating nothing for a year: the dashboard and the bot disagreed about
    what counts as a current price. Carries the real record date, its age, and
    which kind of staleness this is.
    """
    max_age = settings.price_max_age_days
    feed_newest = await _feed_newest_date(db)
    record_day = _as_of_date(row.arrival_date)
    feed_age = (data_refresh.market_today().toordinal() - feed_newest.toordinal()) if feed_newest else None
    # Three genuinely different situations, and the reader must hear the right
    # one: our record is the newest the feed has (nothing published at all), the
    # feed itself is stalled while this crop lags further, or the feed is current
    # and only this mandi is missing this crop.
    at_feed_edge = feed_newest is None or (record_day and feed_newest <= record_day)
    feed_stalled = feed_age is not None and feed_age > max_age
    if at_feed_edge:
        stale_reason = "upstream_not_published"
    elif feed_stalled:
        stale_reason = "upstream_stalled_with_crop_gap"
    else:
        stale_reason = "crop_gap"

    return {
        "type":           "stale_data",
        **region,
        "current_price":  round(current_price, 0),
        "price_as_of":    price_as_of,
        "days_old":       age_days,
        "max_age_days":   max_age,
        "source_market":  row.market,
        "data_source":    data_source,
        "data_quality":   data_quality,
        "feed_newest_date": feed_newest.isoformat() if feed_newest else None,
        "feed_age_days":  feed_age,
        "stale_reason":   stale_reason,
    }


async def get_price_forecast(crop: str, district: str, db: AsyncSession) -> dict:
    if ml_service.MODEL is None:
        return {"type": "error", "detail": ml_service.unavailable_detail()}

    c_pattern = f"%{crop.split()[0]}%"
    d_targets = _DISTRICT_ALIASES.get(district, [district, district[:5]])
    d_conditions = [MandiPrice.district.ilike(f"%{d}%") for d in d_targets]

    # Latest spot record FOR THIS DISTRICT — price, as-of date AND the actual
    # market name (market, not district, is what the model was trained on).
    price_cols = (MandiPrice.modal_price, MandiPrice.arrival_date, MandiPrice.market, MandiPrice.district)
    row = (await db.execute(
        select(*price_cols)
        .where(
            MandiPrice.commodity.ilike(c_pattern),
            or_(*d_conditions),
            MandiPrice.modal_price.isnot(None),
        )
        .order_by(MandiPrice.arrival_date.desc())
        .limit(1)
    )).first()
    data_source = "district"

    # Honest state-level fallback: the crop has mandi records, just none in
    # this district. Label it — the farmer must see WHICH market the price is from.
    if row is None:
        row = (await db.execute(
            select(*price_cols)
            .where(
                MandiPrice.commodity.ilike(c_pattern),
                MandiPrice.modal_price.isnot(None),
            )
            .order_by(MandiPrice.arrival_date.desc())
            .limit(1)
        )).first()
        data_source = "state_fallback"

    if row is None or row.modal_price is None:
        # NO real mandi data anywhere for this crop. Refuse to fabricate a
        # spot price — a made-up number feeding the ML model produces a
        # confident, fully fabricated forecast.
        return {"type": "no_data", "crop": crop, "district": district}

    current_price = float(row.modal_price)
    market_hint   = row.market or district
    price_as_of   = (row.arrival_date.date().isoformat()
                     if isinstance(row.arrival_date, (datetime, date))
                     else str(row.arrival_date or "")[:10])
    age_days      = _age_in_days(row.arrival_date)

    data_quality: list[str] = []
    if data_source == "state_fallback":
        data_quality.append("other_market_price")

    # ── Freshness SLA (P0) ────────────────────────────────
    # An old record is a real price, but it is NOT today's price. Forecasting
    # from it and presenting the result as current is exactly the kind of
    # confident-but-wrong answer this service exists to prevent. Unknown age is
    # treated as unusable: we cannot prove it is fresh.
    if age_days is None:
        data_quality.append("arrival_date_missing")
    elif age_days > settings.price_max_age_days:
        return await _freshness_refusal(
            db, region={"crop": crop, "district": district},
            row=row, current_price=current_price, price_as_of=price_as_of,
            age_days=age_days, data_source=data_source, data_quality=data_quality,
        )

    # ── Arrivals: same resolved market as the spot price ──
    # Querying arrivals by DISTRICT while pricing from a specific MARKET can
    # silently blend two different mandis' data into one forecast, so the market
    # the price came from is the only market asked about.
    arr_cols = (MandiPrice.arrivals_tonnes, MandiPrice.arrival_date, MandiPrice.market)
    arrivals: float | None = None
    arr_row = None
    arrivals_provenance = "unknown"
    if row.market:
        arr_row = (await db.execute(
            select(*arr_cols)
            .where(
                MandiPrice.commodity.ilike(c_pattern),
                MandiPrice.market.ilike(row.market),
                MandiPrice.arrivals_tonnes.isnot(None),
            )
            .order_by(MandiPrice.arrival_date.desc())
            .limit(1)
        )).first()
        if arr_row is not None:
            arrivals = float(arr_row.arrivals_tonnes)
            arrivals_provenance = "recorded"
            if arr_row.market and arr_row.market != row.market:
                arrivals_provenance = "other_market"
                data_quality.append("arrivals_other_market")

    if arrivals is None:
        # Nothing recorded for this mandi — pass 0.0 rather than an invented
        # tonnage, and say so. Arrivals are not a feature of the deployed model,
        # so this changes no number; it only keeps the response truthful about
        # what was actually observed.
        arrivals = _ARRIVALS_UNKNOWN
        arrivals_provenance = "unknown"
        data_quality.append("arrivals_unknown")

    if _age_in_days(arr_row.arrival_date if arr_row is not None else None) not in (None, age_days):
        data_quality.append("arrivals_date_mismatch")

    return await _predict_tail(
        db, region={"crop": crop, "district": district},
        crop=crop, market=market_hint, c_pattern=c_pattern,
        current_price=current_price, arrivals=arrivals,
        price_as_of=price_as_of, age_days=age_days,
        data_source=data_source, source_market=row.market,
        data_quality=data_quality, arrivals_provenance=arrivals_provenance,
    )


async def _predict_tail(
    db: AsyncSession, *,
    region: dict[str, str],
    crop: str,
    market: str | None,
    c_pattern: str,
    current_price: float,
    arrivals: float,
    price_as_of: str,
    age_days: int | None,
    data_source: str,
    source_market: str | None,
    data_quality: list[str],
    arrivals_provenance: str,
) -> dict:
    """
    History probe -> feature build -> predict, shared by the district (bot) and
    market (dashboard) lookups so both channels produce the same contract and
    disclose the same degradations.
    """
    # ── Lag/rolling features need ≥3 real records ─────────
    # Below that, ml_service.build_features substitutes synthetic rolling
    # values (0.97×/0.95× today's price). Honest, but must be disclosed.
    history_count = len((await db.execute(
        select(MandiPrice.modal_price)
        .where(
            MandiPrice.commodity.ilike(c_pattern),
            MandiPrice.market.ilike(market),
            MandiPrice.modal_price.isnot(None),
        )
        .order_by(MandiPrice.arrival_date.desc())
        .limit(3)
    )).all())
    if history_count < 3:
        data_quality.append("history_sparse")

    # ── Trained-vocabulary gate ───────────────────────────
    # A LabelEncoder has no unseen category: encoding a commodity or mandi it
    # never trained on silently produced the code for its first sorted class,
    # so the model scored "Brinjal at Arasikere" regardless of what was asked
    # and published a confident, wrong number. Refuse rather than guess — the
    # dashboard already renders a null forecast for any type other than
    # forecast/anomaly_flagged.
    coverage = ml_service.encoder_coverage(crop, market)
    if coverage["checked"] and not coverage["supported"]:
        return {
            "type":            "unsupported_vocabulary",
            **region,
            "current_price":   round(current_price, 0),
            "price_as_of":     price_as_of,
            "days_old":        age_days,
            "data_source":     data_source,
            "source_market":   source_market,
            "data_quality":    data_quality,
            "arrivals_tonnes": arrivals,
            "arrivals_provenance": arrivals_provenance,
            "missing_axes":    coverage["missing"],
            "anomaly_threshold_pct": None,
            "crop_mape_pct":   None,
            "msp_floor":       None,
            "msp_ratio":       None,
        }

    X = await ml_service.build_features(
        current_price, arrivals, date.today().month, crop, market, db
    )
    try:
        pred_res = ml_service.make_prediction(X, current_price, commodity=crop)
    except ValueError as exc:
        # The 5x sanity guard refusing to publish an implausible forecast is a
        # domain outcome the caller can act on, not a server fault: surface the
        # reason through the standard error path (HTTP 503) instead of a bare 500.
        return {"type": "error", "detail": str(exc)}
    pred = pred_res["pred"]
    low  = pred_res["low"]
    high = pred_res["high"]
    signal, signal_kn = ml_service.price_signal(pred, current_price, crop)
    meta = ml_service.crop_prediction_meta(crop, current_price)

    deviation_pct = abs(pred - current_price) / max(current_price, 1) * 100
    if not math.isfinite(deviation_pct):
        # A corrupt spot price (Postgres Float columns accept NaN/±inf) would
        # put an invalid literal into the JSON body and silently disable the
        # anomaly comparison. Refuse as a domain error instead — same 503 path
        # the sanity guard uses — rather than emit a plausible-looking payload.
        #
        # This must stay ahead of the distribution gate below: every comparison
        # against a NaN is False, so a non-finite price would be reported as
        # "outside the defensible range" and answer a data-corruption fault with
        # a calibration message.
        return {
            "type": "error",
            "detail": f"Non-finite forecast deviation for {crop} at {market} — refusing to publish.",
        }

    # ── Historical-range validation ───────────────────────
    # Passing the vocabulary gate confirms the model was asked about a category
    # it knows; it does not confirm the resulting number is credible. Compare
    # the point estimate against the distribution this crop actually has at
    # this mandi and withhold the headline figure when the model disagrees with
    # its own evidence base (see the calibration constants in this module).
    dist = (await db.execute(
        select(func.min(MandiPrice.modal_price),
               func.max(MandiPrice.modal_price),
               func.avg(MandiPrice.modal_price),
               func.stddev(MandiPrice.modal_price),
               func.count(MandiPrice.id))
        .where(
            MandiPrice.commodity.ilike(c_pattern),
            MandiPrice.market.ilike(market),
            MandiPrice.modal_price.isnot(None),
            MandiPrice.arrival_date >= date.today() - timedelta(days=730),
        )
    )).one()
    hist_min, hist_max, hist_mean, hist_sd, hist_count = dist[:5]
    if (hist_count >= 3 and hist_min is not None and hist_max is not None
            and math.isfinite(hist_min) and math.isfinite(hist_max)
            and math.isfinite(pred)):
        spread = hist_max - hist_min
        # A zero dispersion (one repeated price) would collapse the band to the
        # MAE term alone, so fall back to that term rather than to ±0.
        band = max(
            _FORECAST_BAND_MIN_PCT_OF_SPREAD * spread,
            _FORECAST_BAND_MIN_MAE_MULTIPLE * (hist_mean or current_price)
            * (meta["crop_mape_pct"] or 0.0) / 100.0,
        )
        defensible_low  = hist_min - band
        defensible_high = hist_max + band
        if not (defensible_low <= pred <= defensible_high):
            return {
                "type":            "model_validation_warning",
                **region,
                "current_price":   round(current_price, 0),
                "price_as_of":     price_as_of,
                "days_old":        age_days,
                "data_source":     data_source,
                "source_market":   source_market,
                "data_quality":    data_quality,
                "arrivals_tonnes": arrivals,
                "arrivals_provenance": arrivals_provenance,
                # Disclosed but deliberately not presented as a forecast: the
                # reader can see how far off the model is, not just that it is.
                "model_raw_forecast": round(pred, 0),
                "historical_min":  round(hist_min, 0),
                "historical_max":  round(hist_max, 0),
                "historical_mean": round(hist_mean, 0) if hist_mean else None,
                "historical_stddev": round(hist_sd, 0) if hist_sd else None,
                "historical_records": hist_count,
                "band_width":      round(band, 0),
                "defensible_low":  round(defensible_low, 0),
                "defensible_high": round(defensible_high, 0),
                "crop_mape_pct":   meta["crop_mape_pct"],
                "anomaly_threshold_pct": None,
            }

    # MAPE-aware gate: on volatile crops (Tomato/Marigold ~28-31% benchmark
    # error) a fixed 30% flag would label the model's own noise a market
    # SPIKE/CRASH. The effective threshold travels in the response so every
    # channel discloses the same number instead of hardcoding "30%".
    anomaly_threshold = ml_service.anomaly_threshold_pct(crop, meta["crop_mape_pct"])
    is_anomaly    = deviation_pct > anomaly_threshold
    anomaly_type  = "SPIKE" if pred > current_price else ("CRASH" if pred < current_price else "NORMAL")

    base = {
        **region,
        "current_price": round(current_price, 0),
        "price_as_of":   price_as_of,
        "days_old":      age_days,
        "data_source":   data_source,
        "source_market": source_market,
        "data_quality":  data_quality,
        "arrivals_tonnes": arrivals,
        "arrivals_provenance": arrivals_provenance,
        "forecast":      round(pred, 0),
        "lower":         round(low, 0),
        "upper":         round(high, 0),
        "signal":        signal,
        "signal_kannada":signal_kn,
        "is_anomaly":    is_anomaly,
        "anomaly_type":  anomaly_type,
        "deviation_pct": round(deviation_pct, 1),
        "anomaly_threshold_pct": round(anomaly_threshold, 1),
        "crop_mape_pct": meta["crop_mape_pct"],
        "msp_floor":     meta["msp_floor"],
        "msp_ratio":     meta.get("msp_ratio"),
    }

    if is_anomaly:
        return {"type": "anomaly_flagged", **base}
    return {"type": "forecast", **base}


async def get_market_forecast(
    crop: str,
    market: str,
    db: AsyncSession,
    *,
    scenario_price: float | None = None,
    scenario_arrivals: float | None = None,
) -> dict:
    """
    Forecast for one NAMED mandi, behind the same freshness gate as the bot.

    This exists because `/prices/predict` was a second, ungated implementation:
    it forecasted from whatever `current_price` the caller put in the URL, with
    no record lookup and no age check, so the dashboard could display a
    months-old or entirely invented price as a live prediction. Here the price is
    resolved from the database first; a caller-supplied value is treated as an
    explicitly labelled what-if scenario, never as a verified observation.
    """
    if ml_service.MODEL is None:
        return {"type": "error", "detail": ml_service.unavailable_detail()}

    c_pattern = f"%{crop.split()[0]}%"
    price_cols = (MandiPrice.modal_price, MandiPrice.arrival_date, MandiPrice.market,
                  MandiPrice.district, MandiPrice.arrivals_tonnes)
    row = (await db.execute(
        select(*price_cols)
        .where(
            MandiPrice.commodity.ilike(c_pattern),
            MandiPrice.market.ilike(f"%{market}%"),
            MandiPrice.modal_price.isnot(None),
        )
        .order_by(MandiPrice.arrival_date.desc())
        .limit(1)
    )).first()

    if row is None or row.modal_price is None:
        # No fabricated spot price, and no forecast built on one.
        return {"type": "no_data", "crop": crop, "market": market}

    verified_price = float(row.modal_price)
    current_price  = verified_price
    price_as_of    = (row.arrival_date.date().isoformat()
                      if isinstance(row.arrival_date, (datetime, date))
                      else str(row.arrival_date or "")[:10])
    age_days       = _age_in_days(row.arrival_date)
    data_source    = "market"
    arrivals_provenance = "recorded" if row.arrivals_tonnes is not None else "unknown"
    arrivals       = (float(row.arrivals_tonnes) if row.arrivals_tonnes is not None
                      else _ARRIVALS_UNKNOWN)

    data_quality: list[str] = []
    if scenario_price is not None and abs(float(scenario_price) - verified_price) > 0.01:
        # A caller may explore "what if the price were X", but the answer is then
        # a scenario, not a market forecast — and the record's real age still
        # gates it, because an old base price does not become current by editing it.
        current_price = float(scenario_price)
        data_source = "caller_scenario"
        data_quality.append("price_override")
        if verified_price > 0 and abs(current_price - verified_price) / verified_price > 0.25:
            data_quality.append("price_diverges_from_mandi")
    if scenario_arrivals is not None and abs(float(scenario_arrivals) - arrivals) > 0.01:
        arrivals = float(scenario_arrivals)
        arrivals_provenance = "caller_scenario"
        data_quality.append("arrivals_override")
    if row.arrivals_tonnes is None:
        data_quality.append("arrivals_unknown")

    # Same SLA, same refusal, same provenance fields as every other channel.
    if age_days is None:
        data_quality.append("arrival_date_missing")
    elif age_days > settings.price_max_age_days:
        return await _freshness_refusal(
            db, region={"crop": crop, "market": market},
            row=row, current_price=verified_price, price_as_of=price_as_of,
            age_days=age_days, data_source=data_source, data_quality=data_quality,
        )

    return await _predict_tail(
        db, region={"crop": crop, "market": market, "district": row.district},
        crop=crop, market=row.market, c_pattern=c_pattern,
        current_price=current_price, arrivals=arrivals,
        price_as_of=price_as_of, age_days=age_days,
        data_source=data_source, source_market=row.market,
        data_quality=data_quality, arrivals_provenance=arrivals_provenance,
    )
