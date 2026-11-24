// frontend/tests/saturationMap.test.mjs — Saturation Index honesty tests.
// Run with `npm test` (node's built-in test runner; no jsdom required).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  buildRadarRow,
  resolveMapSource,
  tileFallbackNote,
  tileUrlFor,
  outlinePointsViewBox,
  configuredTileUrl,
  TILE_PROVIDER,
  TILE_ATTRIBUTION,
} from '../src/saturationMap.js';

// The exact payload shape /saturation/Kolar/Tomato returns (backend
// farmer_service.calc_saturation): real percentage + documented reference area.
const KOLAR_TOMATO = {
  district: 'Kolar', crop: 'Tomato', season: 'Rabi',
  saturation_pct: 0.0, total_area: 0.0, reference_area_acres: 12000.0,
  reference_basis: 'district_crop_statistics',
  risk_level: 'LOW', risk_kannada: 'ಸೂಕ್ತ ಪ್ರಮಾಣ', emoji: '🟢', farmer_count: 0,
};

test('a valid saturation response yields the real percentage and reference acreage', () => {
  const row = buildRadarRow({ district: 'Kolar', crop: 'Tomato' }, KOLAR_TOMATO);
  assert.equal(row.saturation, 0.0);
  assert.equal(row.saturationUnavailable, false);
  assert.equal(row.referenceAreaAcres, 12000.0);
  assert.equal(row.status, 'LOW');
});

test('intervention bands ride on the backend figure, never replace it', () => {
  const mid = buildRadarRow({}, { ...KOLAR_TOMATO, saturation_pct: 45.0 });
  assert.equal(mid.status, 'MEDIUM');
  assert.equal(mid.action, 'Cap Fertilizer Loans');
  const high = buildRadarRow({}, { ...KOLAR_TOMATO, saturation_pct: 72.5 });
  assert.equal(high.status, 'HIGH');
  assert.equal(high.action, 'CEASE SUBSIDIZED CREDIT');
  assert.equal(high.saturation, 72.5);
});

test('a failed pair fetch is labeled unavailable — never a fabricated 0.0%', () => {
  // fetchJson's per-pair catch returns null; the old mapping coerced that to
  // "0.0% LOW", i.e. a fake all-clear for a district we know nothing about.
  const row = buildRadarRow({ district: 'Kolar', crop: 'Tomato' }, null);
  assert.equal(row.saturation, null);
  assert.equal(row.saturationUnavailable, true);
  assert.equal(row.status, 'UNKNOWN');
  assert.equal(row.action, 'Data unavailable');
  assert.equal(row.district, 'Kolar'); // identity survives the failure
  const junk = buildRadarRow({ district: 'Kolar', crop: 'Tomato' }, { risk_level: 'LOW' });
  assert.equal(junk.saturationUnavailable, true);
});

test('district/crop parameters are URL-encoded into the saturation request', () => {
  // Source assertion: the screen must keep calling the real endpoint with the
  // pair it was given — the wiring an endpoint-level 200 can never prove.
  const src = readFileSync(new URL('../src/pages/InsightsView.jsx', import.meta.url), 'utf8');
  assert.match(
    src,
    /fetchJson\(\s*apiUrl\(`\/saturation\/\$\{encodeURIComponent\(q\.district\)\}\/\$\{encodeURIComponent\(q\.crop\)\}\?season=\$\{encodeURIComponent\(season\)\}`\)/,
    'InsightsView must request /saturation/{district}/{crop}?season={season} with encoded parameters'
  );
});

test('the screen has no API-required placeholder in any user-visible text', () => {
  // Comments are stripped first: the source deliberately QUOTES the CartoDB
  // "API KEY REQUIRED" watermark to explain why we stopped using tiles, and
  // that prose must not trip the check. Only live code/text matters here.
  const loadCode = (p) => readFileSync(new URL(p, import.meta.url), 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '')            // block comments
    .split('\n')
    .filter((line) => !line.trim().startsWith('//'))  // line comments
    .join('\n');
  for (const file of ['../src/pages/InsightsView.jsx', '../src/saturationMap.js']) {
    assert.doesNotMatch(loadCode(file), /API[ -]required|api key|apiKey|requires? an API/i,
      `${file} must not tell the user an external API is required`);
  }
});

test('map source: defaults to clean OpenStreetMap tiles without CartoDB watermark', () => {
  // With no VITE_MAP_TILE_URL override, the screen defaults to standard OpenStreetMap
  assert.equal(configuredTileUrl(), TILE_PROVIDER);
  assert.match(TILE_PROVIDER, /openstreetmap\.org/);
  assert.doesNotMatch(TILE_PROVIDER, /cartocdn\.com/, 'CartoDB watermark provider must not be used');
  assert.deepEqual(resolveMapSource({ tileUrl: TILE_PROVIDER }), { kind: 'tiles', tileUrl: TILE_PROVIDER });
  // Failure / offline falls back cleanly to local-canvas without crashing
  assert.deepEqual(resolveMapSource({ tileUrl: null }), { kind: 'local-canvas', tileUrl: null });
  assert.equal(resolveMapSource({ tileUrl: TILE_PROVIDER, tilesFailed: true }).kind, 'local-canvas');
  assert.equal(resolveMapSource({ tileUrl: TILE_PROVIDER, online: false }).tileUrl, null);
});

test('map source: zero natural dimension tile triggers fallback to local canvas', () => {
  const failedZeroDim = resolveMapSource({ tileUrl: TILE_PROVIDER, tilesFailed: true, online: true });
  assert.equal(failedZeroDim.kind, 'local-canvas');
  assert.equal(failedZeroDim.tileUrl, null);
});

test('the offline note is honest: no API claim, live data still shown', () => {
  const note = tileFallbackNote();
  assert.match(note, /no external tile provider/);
  assert.match(note, /live backend data/);
  assert.doesNotMatch(note, /API/i);
});

test('the fallback canvas is decorative geometry only and is labelled as such', () => {
  const pts = outlinePointsViewBox();
  const pairs = pts.split(' ');
  assert.ok(pairs.length >= 12, 'outline must have enough vertices to read as a state');
  for (const p of pairs) {
    const [x, y] = p.split(',').map(Number);
    assert.ok(Number.isFinite(x) && x >= 0 && x <= 100);
    assert.ok(Number.isFinite(y) && y >= 0 && y <= 100);
  }
  // Source assertion: the canvas block carries the explanatory note, so a
  // drawn outline can never be mistaken for real map data.
  const src = readFileSync(new URL('../src/pages/InsightsView.jsx', import.meta.url), 'utf8');
  assert.match(src, /\{tileFallbackNote\(\)\}/);
});

test('tile failure degrades the basemap without blocking or faking saturation data', () => {
  // Source assertions on the wiring itself: TileLayer only renders from the
  // resolved source, tileerror is observed, and unavailable rows are labeled.
  const src = readFileSync(new URL('../src/pages/InsightsView.jsx', import.meta.url), 'utf8');
  assert.match(src, /<TileLayer[\s\S]*?url=\{mapSource\.tileUrl\}[\s\S]*?eventHandlers=\{tileEventHandlers\}/);
  assert.match(src, /row\.saturationUnavailable \? 'N\/A · no data'/);
  assert.match(src, /node\.saturationUnavailable \? 'Data unavailable'/);
  assert.doesNotMatch(src, /Number\(item\.saturation_pct \?\? 0\.0\)/,
    'the old ?? 0.0 coercion must not come back');
});

test('loading state is cleared on both success and backend failure', () => {
  const src = readFileSync(new URL('../src/pages/InsightsView.jsx', import.meta.url), 'utf8');
  // The OUTER chain settles the spinner; the first `.catch` in the file is the
  // per-pair guard inside Promise.all and must not be mistaken for it.
  const successBranch = src.slice(src.indexOf('.then(radar =>'), src.lastIndexOf('.catch(err =>'));
  const failureBranch = src.slice(src.lastIndexOf('.catch(err =>'));
  assert.match(successBranch, /setLoading\(false\)/);
  assert.match(failureBranch, /setLoading\(false\)/);
  assert.match(failureBranch, /setErrorNote\(/, 'total backend failure must say so, not spin forever');
});

// ── Season resolution: one season, one number, everywhere ───────────────────
// Payloads captured from the local API against the real 346 declarations
// (backend/services/farmer_service.py::calc_saturation).

// GET /saturation/Kolar/Tomato?season=Rabi%202026-2027 — the cycle November
// derives, which has no declarations at all.
const KOLAR_TOMATO_FALLBACK = {
  district: 'Kolar', crop: 'Tomato', saturation_pct: 0.1, risk_level: 'LOW',
  farmer_count: 7, total_area: 16.5, reference_area_acres: 12000,
  reference_basis: 'district_crop_statistics',
  season: 'Kharif 2026', season_requested: 'Rabi 2026-2027',
  season_match: 'latest_available', season_fallback: true,
  has_declarations: true,
  seasons_with_data: ['kharif_2026', 'Kharif 2026'],
};

// GET /saturation/Mysuru/Paddy?season=Kharif%202026 — nothing declared.
const MYSURU_PADDY_NONE = {
  district: 'Mysuru', crop: 'Paddy', saturation_pct: 0.0, risk_level: 'LOW',
  farmer_count: 0, total_area: 0, reference_area_acres: 5000,
  reference_basis: 'state_average_fallback',
  season: 'Kharif 2026', season_requested: 'Kharif 2026',
  season_match: 'none', season_fallback: false, has_declarations: false,
};

test('a latest-season fallback keeps the real number and discloses the season', () => {
  const row = buildRadarRow({ district: 'Kolar', crop: 'Tomato' }, KOLAR_TOMATO_FALLBACK);
  assert.equal(row.saturation, 0.1);
  assert.equal(row.saturationUnavailable, false);
  assert.equal(row.farmerCount, 7);
  assert.equal(row.season, 'Kharif 2026');
  assert.equal(row.seasonRequested, 'Rabi 2026-2027');
  assert.equal(row.seasonFallback, true);
});

test('no declarations is unavailable, not a reassuring 0% LOW', () => {
  const row = buildRadarRow({ district: 'Mysuru', crop: 'Paddy' }, MYSURU_PADDY_NONE);
  assert.equal(row.saturationUnavailable, true);
  assert.equal(row.saturation, null);
  assert.equal(row.status, 'NO DATA');
  assert.equal(row.action, 'No sowing declarations');
  assert.notEqual(row.status, 'LOW', '0.0% with no data behind it must not read as an all-clear');
});

test('every saturation request states the season it is asking about', () => {
  // A request without a season let the backend answer for a cycle that has no
  // declarations, and both places rendered the result as 0%. The header chip,
  // the radar and the forecast screen must all send one explicitly.
  const files = ['../src/components/Layout.jsx', '../src/pages/InsightsView.jsx',
                 '../src/pages/TerminalView.jsx'];
  for (const file of files) {
    const src = readFileSync(new URL(file, import.meta.url), 'utf8');
    for (const line of src.split('\n').filter((l) => l.includes('/saturation/'))) {
      assert.match(line, /season=/, `${file}: saturation request omits the season`);
    }
  }
});
