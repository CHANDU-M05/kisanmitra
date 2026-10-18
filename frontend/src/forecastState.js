// src/forecastState.js — pure view logic for the Market Prices screen.
//
// Extracted from TerminalView.jsx so the honesty rules can be tested without a
// browser: what may be displayed as a forecast, and what must be displayed as
// stale or missing instead. TerminalView previously took `history[last].price`
// (which could be a fabricated seasonal value), sent it back to the API as
// `current_price` along with `arrivals_tonnes=100.0`, and rendered whatever came
// back as a live prediction.
//
// The rules encoded here:
//   * A forecast number exists ONLY when the server says type is forecast or
//     anomaly_flagged. Everything else clears every forecast-derived value.
//   * `predicted_price: null` is not a zero, and an absent record is not a price.
//   * A caller-supplied price is a scenario, and is labelled as one.

export const FEED_STATE = {
  LOADING: 'loading',
  OK: 'ok',
  SCENARIO: 'scenario',
  STALE: 'stale',
  NO_DATA: 'no_data',
  ERROR: 'error',
};

const NO_FORECAST = Object.freeze({
  hasForecast: false,
  predicted: null,
  low: null,
  high: null,
  signal: null,
  trend: 'NEUTRAL',
});

function trendForSignal(signal) {
  const s = typeof signal === 'string' ? signal : '';
  if (s.includes('falling') || s.includes('FALL')) {
    return { trend: 'BEARISH', recommendation: 'HALT PLANTING — CRITICAL OVERSUPPLY IN MARKET' };
  }
  if (s.includes('rising') || s.includes('WAIT')) {
    return { trend: 'BULLISH', recommendation: 'STABLE PATHWAY — SECURE ACREAGE INCREASES' };
  }
  return { trend: 'NEUTRAL', recommendation: 'MONITOR ACREAGES — MARKET ABSORPTION STABLE' };
}

function provenanceOf(pred) {
  return {
    price_as_of: pred.price_as_of ?? null,
    days_old: pred.days_old ?? null,
    data_source: pred.data_source ?? null,
    source_market: pred.source_market ?? null,
    price_provenance: pred.price_provenance ?? null,
    arrivals_tonnes: pred.arrivals_tonnes ?? null,
    arrivals_provenance: pred.arrivals_provenance ?? null,
    data_quality: Array.isArray(pred.data_quality) ? pred.data_quality : [],
    stale_reason: pred.stale_reason ?? null,
    max_age_days: pred.max_age_days ?? null,
    feed_newest_date: pred.feed_newest_date ?? null,
    feed_age_days: pred.feed_age_days ?? null,
    message: pred.message ?? null,
  };
}

/**
 * Map a `/prices/predict` response onto what the screen may show.
 * Anything other than an explicit forecast/anomaly result yields hasForecast=false
 * and null numbers, so no downstream code can render a zero or a stale value as
 * a live prediction.
 */
export function deriveForecastView(pred) {
  if (!pred || typeof pred !== 'object') {
    return {
      state: FEED_STATE.ERROR, ...NO_FORECAST,
      cropMeta: { crop_mape_pct: null, msp_floor: null, msp_ratio: null },
      anomaly: { is_anomaly: false, deviation_pct: 0, anomaly_type: 'NORMAL' },
      recommendation: 'FORECAST SERVICE UNAVAILABLE',
      provenance: provenanceOf({}),
    };
  }

  const provenance = provenanceOf(pred);

  if (pred.type === 'forecast' || pred.type === 'anomaly_flagged') {
    const { trend, recommendation } = trendForSignal(pred.signal);
    const isScenario = pred.price_provenance === 'caller_scenario'
      || pred.data_source === 'caller_scenario';
    return {
      state: isScenario ? FEED_STATE.SCENARIO : FEED_STATE.OK,
      hasForecast: pred.predicted_price != null,
      predicted: pred.predicted_price ?? null,
      low: pred.confidence_low ?? null,
      high: pred.confidence_high ?? null,
      signal: pred.signal ?? null,
      signalKannada: pred.signal_kannada ?? null,
      trend: pred.predicted_price != null ? trend : 'NEUTRAL',
      recommendation: pred.predicted_price != null
        ? recommendation
        : 'FORECAST UNAVAILABLE — NO VERIFIED PRICE',
      cropMeta: {
        crop_mape_pct: pred.crop_mape_pct ?? null,
        msp_floor: pred.msp_floor ?? null,
        msp_ratio: pred.msp_ratio ?? null,
      },
      anomaly: {
        is_anomaly: Boolean(pred.is_anomaly),
        deviation_pct: pred.deviation_pct || 0,
        anomaly_type: pred.anomaly_type || 'NORMAL',
      },
      provenance,
    };
  }

  if (pred.type === 'stale_data') {
    const age = Number.isFinite(pred.days_old) ? `${pred.days_old} days old` : 'undated';
    return {
      state: FEED_STATE.STALE, ...NO_FORECAST,
      cropMeta: { crop_mape_pct: null, msp_floor: null, msp_ratio: null },
      anomaly: { is_anomaly: false, deviation_pct: 0, anomaly_type: 'NORMAL' },
      recommendation: `NO FORECAST — LATEST RECORD IS ${age} (LIMIT ${pred.max_age_days ?? 3} DAYS)`,
      provenance,
    };
  }

  if (pred.type === 'no_data') {
    return {
      state: FEED_STATE.NO_DATA, ...NO_FORECAST,
      cropMeta: { crop_mape_pct: null, msp_floor: null, msp_ratio: null },
      anomaly: { is_anomaly: false, deviation_pct: 0, anomaly_type: 'NORMAL' },
      recommendation: 'NO VERIFIED MANDI RECORD FOR THIS MARKET',
      provenance,
    };
  }

  return {
    state: FEED_STATE.ERROR, ...NO_FORECAST,
    cropMeta: { crop_mape_pct: null, msp_floor: null, msp_ratio: null },
    anomaly: { is_anomaly: false, deviation_pct: 0, anomaly_type: 'NORMAL' },
    recommendation: 'FORECAST SERVICE UNAVAILABLE',
    provenance,
  };
}

/**
 * Banner for the current data state. Stale and no-data states must win over the
 * scenario styling: an empty market is not a "simulated scenario".
 */
export function feedBanner(view, { crop, market, isSimulated, scenarioName }) {
  const p = view.provenance || {};
  switch (view.state) {
    case FEED_STATE.STALE:
      return {
        tone: 'unavailable',
        text: `NO CURRENT FORECAST — ${String(market).toUpperCase()} LAST REPORTED ${p.price_as_of || 'ON AN UNKNOWN DATE'}`
          + (p.stale_reason === 'upstream_not_published' ? ' (NOTHING PUBLISHED YET)' : ''),
      };
    case FEED_STATE.NO_DATA:
      return {
        tone: 'unavailable',
        text: `NO MANDI RECORD FOR ${String(crop).toUpperCase()} IN ${String(market).toUpperCase()}`,
      };
    case FEED_STATE.ERROR:
      return { tone: 'unavailable', text: 'FORECAST SERVICE UNAVAILABLE — TRY AGAIN SHORTLY' };
    case FEED_STATE.LOADING:
      return { tone: 'muted', text: 'LOADING VERIFIED MANDI DATA…' };
    case FEED_STATE.SCENARIO:
      return { tone: 'scenario', text: `WHAT-IF SCENARIO — PRICE SUPPLIED BY YOU, NOT THE MANDI (${String(crop).toUpperCase()})` };
    default:
      if (isSimulated) {
        return { tone: 'scenario', text: `SIMULATED — ${String(scenarioName || 'SCENARIO').toUpperCase()} · NOT LIVE DATA` };
      }
      return { tone: view.trend, text: view.recommendation };
  }
}

/**
 * Chart rows: real history always, the projected spline only when a forecast
 * actually exists. Modifiers reproduce the on-screen scenario sliders, which are
 * explicitly labelled as simulations of an existing model output.
 */
export function buildChartData(history, view, { envDeviation = 0, subsidyLevel = 'Normalized', steps = 6 } = {}) {
  if (!Array.isArray(history) || history.length === 0) return [];

  const rows = history.map((item) => ({
    day: String(item.date).substring(5),
    historical: item.price,
    forecast: null,
    confidenceHigh: null,
    confidenceLow: null,
  }));

  if (!view || !view.hasForecast || view.predicted == null) return rows;

  const lastHist = rows[rows.length - 1];
  let modifier = 1.0 + (envDeviation * -0.006);
  if (subsidyLevel === 'Inflation') modifier += 0.12;
  if (subsidyLevel === 'Relief') modifier -= 0.08;

  const predicted = Math.round(view.predicted * modifier);
  const high = Math.round((view.high ?? view.predicted) * modifier);
  const low = Math.round((view.low ?? view.predicted) * modifier);
  const priceStep = (predicted - lastHist.historical) / steps;

  lastHist.forecast = lastHist.historical;
  lastHist.confidenceHigh = lastHist.historical;
  lastHist.confidenceLow = lastHist.historical;

  for (let i = 1; i <= steps; i++) {
    const stepPrice = Math.round(lastHist.historical + i * priceStep);
    const progressRatio = i / steps;
    rows.push({
      day: `T+${i * 10}`,
      historical: null,
      forecast: stepPrice,
      confidenceHigh: Math.round(stepPrice + (high - stepPrice) * progressRatio),
      confidenceLow: Math.round(stepPrice - (stepPrice - low) * progressRatio),
    });
  }
  return rows;
}

/** Latest verified price, or null — never a hardcoded stand-in. */
export function latestHistoricalPrice(history) {
  if (!Array.isArray(history) || history.length === 0) return null;
  const last = history[history.length - 1];
  return Number.isFinite(last?.price) ? last.price : null;
}
