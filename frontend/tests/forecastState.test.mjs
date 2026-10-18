// frontend/tests/forecastState.test.mjs — honesty rules for the price screen.
// Run with `npm test` (node's built-in test runner; no extra dependencies).
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { readFileSync } from 'node:fs';
import {
  buildChartData,
  deriveForecastView,
  feedBanner,
  latestHistoricalPrice,
} from '../src/forecastState.js';

const FORECAST = {
  type: 'forecast',
  commodity: 'Tomato',
  market: 'Kolar',
  current_price: 2000,
  price_as_of: '2026-10-16',
  days_old: 1,
  predicted_price: 2100,
  confidence_low: 1700,
  confidence_high: 2500,
  signal: 'NEUTRAL — Monitor weekly',
  is_anomaly: false,
  anomaly_type: null,
  deviation_pct: 5,
  crop_mape_pct: 27.84,
  msp_floor: null,
  msp_ratio: null,
  data_source: 'market',
  price_provenance: 'verified_mandi',
  arrivals_tonnes: 80,
  arrivals_provenance: 'recorded',
  data_quality: [],
};

const HISTORY = [
  { date: '2026-10-14', price: 1900, is_synthetic: false },
  { date: '2026-10-16', price: 2000, is_synthetic: false },
];

test('a verified forecast renders numbers and a trend', () => {
  const view = deriveForecastView(FORECAST);
  assert.equal(view.state, 'ok');
  assert.equal(view.hasForecast, true);
  assert.equal(view.predicted, 2100);
  assert.equal(view.trend, 'NEUTRAL');
  assert.equal(view.provenance.price_as_of, '2026-10-16');
});

test('an anomaly response is still a forecast', () => {
  const view = deriveForecastView({ ...FORECAST, type: 'anomaly_flagged', is_anomaly: true, anomaly_type: 'CRASH', deviation_pct: 42 });
  assert.equal(view.hasForecast, true);
  assert.equal(view.anomaly.is_anomaly, true);
  assert.equal(view.anomaly.anomaly_type, 'CRASH');
});

test('a caller-supplied price is shown as a what-if scenario', () => {
  const view = deriveForecastView({
    ...FORECAST, data_source: 'caller_scenario', price_provenance: 'caller_scenario',
    data_quality: ['price_override'],
  });
  assert.equal(view.state, 'scenario');
  const banner = feedBanner(view, { crop: 'Tomato', market: 'Kolar' });
  assert.match(banner.text, /WHAT-IF SCENARIO/);
  assert.deepEqual(view.provenance.data_quality, ['price_override']);
});

test('a stale response produces no forecast and no zero', () => {
  const view = deriveForecastView({
    type: 'stale_data', current_price: 1800, price_as_of: '2026-08-25', days_old: 53,
    max_age_days: 3, market: 'Kolar', source_market: 'Kolar',
    stale_reason: 'upstream_not_published', feed_newest_date: '2026-08-25', feed_age_days: 53,
    predicted_price: null, confidence_low: null, confidence_high: null, signal: null,
    data_quality: [],
  });
  assert.equal(view.state, 'stale');
  assert.equal(view.hasForecast, false);
  assert.equal(view.predicted, null);
  assert.equal(view.low, null);
  assert.equal(view.high, null);
  assert.equal(view.cropMeta.crop_mape_pct, null);
  assert.match(view.recommendation, /NO FORECAST/);
  assert.match(view.recommendation, /53 days old/);

  const banner = feedBanner(view, { crop: 'Tomato', market: 'Kolar' });
  assert.equal(banner.tone, 'unavailable');
  assert.match(banner.text, /NO CURRENT FORECAST/);
  assert.match(banner.text, /LAST REPORTED 2026-08-25/);
  assert.match(banner.text, /NOTHING PUBLISHED YET/);
});

test('a missing record is reported as missing, not priced', () => {
  const view = deriveForecastView({ type: 'no_data', crop: 'Tomato', market: 'Kolar' });
  assert.equal(view.state, 'no_data');
  assert.equal(view.hasForecast, false);
  assert.equal(view.predicted, null);
  const banner = feedBanner(view, { crop: 'Tomato', market: 'Kolar' });
  assert.match(banner.text, /NO MANDI RECORD FOR TOMATO IN KOLAR/);
});

test('an unusable response body fails closed', () => {
  for (const bad of [null, undefined, {}, 'nope']) {
    const view = deriveForecastView(bad);
    assert.equal(view.hasForecast, false);
    assert.equal(view.predicted, null);
    assert.equal(['error', 'no_data'].includes(view.state), true);
  }
});

test('the chart draws history only when there is no forecast', () => {
  const stale = deriveForecastView({ type: 'stale_data', days_old: 53, price_as_of: '2026-08-25', max_age_days: 3, data_quality: [] });
  const rows = buildChartData(HISTORY, stale);
  assert.equal(rows.length, 2);
  assert.equal(rows.some(r => r.forecast != null), false);
  assert.deepEqual(rows.map(r => r.historical), [1900, 2000]);
});

test('the chart projects the spline only from a real forecast', () => {
  const rows = buildChartData(HISTORY, deriveForecastView(FORECAST));
  assert.equal(rows.length, 8);            // 2 historical + 6 projected
  assert.equal(rows[rows.length - 1].day, 'T+60');
  assert.equal(rows[rows.length - 1].forecast, 2100);
});

test('scenario sliders are labelled relative to a real forecast', () => {
  const rows = buildChartData(HISTORY, deriveForecastView(FORECAST), { envDeviation: 0, subsidyLevel: 'Inflation' });
  assert.equal(rows[rows.length - 1].forecast, Math.round(2100 * 1.12));
});

test('latest price has no hardcoded stand-in', () => {
  assert.equal(latestHistoricalPrice([]), null);
  assert.equal(latestHistoricalPrice(undefined), null);
  assert.equal(latestHistoricalPrice([{ date: '2026-10-16', price: 2000 }]), 2000);
  assert.equal(buildChartData([], deriveForecastView(FORECAST)).length, 0);
});

test('simulated styling never overrides an unavailable market', () => {
  const stale = deriveForecastView({ type: 'stale_data', days_old: 53, price_as_of: '2026-08-25', max_age_days: 3, data_quality: [] });
  const banner = feedBanner(stale, { crop: 'Tomato', market: 'Kolar', isSimulated: true, scenarioName: 'Drought' });
  assert.equal(banner.tone, 'unavailable');
  assert.doesNotMatch(banner.text, /SIMULATED/);
});

test('the dashboard no longer divides acreage by an invented capacity', () => {
  // 175 acres was hardcoded as "hub capacity" in two places and produced a
  // saturation percentage that no backend endpoint or bot agreed with.
  // Full-line comments are stripped first: this file explains the old number.
  const load = (p) => readFileSync(new URL(p, import.meta.url), 'utf8')
    .split('\n')
    .filter((line) => !line.trim().startsWith('//'))
    .join('\n');
  for (const file of ['../src/pages/TerminalView.jsx', '../src/components/Layout.jsx']) {
    assert.doesNotMatch(load(file), new RegExp('/\\s*175(?:\\.0)?\\b'), `hardcoded 175-acre denominator in ${file}`);
    assert.match(load(file), /saturation_pct/, `${file} must use the backend's saturation figure`);
  }
});
