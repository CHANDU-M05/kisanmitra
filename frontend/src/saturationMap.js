// src/saturationMap.js — map-source and honesty helpers for the Saturation Index.
//
// Why this exists: the saturation SCREEN previously hard-depended on one
// external raster-tile provider (CartoDB). When that provider was blocked,
// rate-limited or simply offline, the map went blank/grey behind the live
// markers and the screen read like an unexplained "an API is required" wall —
// even though the saturation NUMBERS come from our own backend
// (`/saturation/{district}/{crop}`), which needs no third-party API at all.
//
// The rule this module encodes:
//   1. The basemap is a nice-to-have. If its tiles fail, fall back to a local
//      vector canvas — never leave the user staring at a grey pane.
//   2. A failed tile fetch must never block or fake saturation data, and a
//      missing saturation value must never be drawn as "0.0%".
import { useEffect, useMemo, useState } from 'react';

export const TILE_PROVIDER = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
export const TILE_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors';

// Exact provider URL per theme. Standard OpenStreetMap is the primary clean raster tile provider.
export function tileUrlFor(theme, provider = TILE_PROVIDER) {
  return provider;
}

// Configured tile URL from environment (VITE_MAP_TILE_URL), or falls back to standard OpenStreetMap.
export function configuredTileUrl() {
  return import.meta.env?.VITE_MAP_TILE_URL || TILE_PROVIDER;
}

// The map source is chosen honestly: tiles ONLY when a provider is configured
// and reachable; otherwise the local themed canvas. No watermark, no dependency.
export function resolveMapSource({ tileUrl = configuredTileUrl(), tilesFailed = false, online = true } = {}) {
  if (!tileUrl || !online || tilesFailed) return { kind: 'local-canvas', tileUrl: null };
  return { kind: 'tiles', tileUrl };
}

// Honest one-liner shown when no raster basemap is active. It must not claim an
// API is required — the markers are live data from our own backend.
export function tileFallbackNote() {
  return 'Minimal map (no external tile provider) \u2014 saturation markers show live backend data, not simulated values.';
}

// Karnataka outline as [lat, lng] pairs — coarse (state-identification level),
// clearly decorative, and labeled as such wherever it is drawn. It carries no
// data: it exists so a failed tile layer does not look like a broken feature.
export const KARNATAKA_OUTLINE = [
  [13.2, 74.7], [12.8, 74.8], [12.9, 75.2], [13.0, 75.7], [13.2, 76.1],
  [12.6, 76.5], [12.3, 76.6], [11.9, 76.9], [12.1, 77.2], [12.7, 77.6],
  [13.0, 77.6], [13.4, 77.7], [13.6, 77.4], [14.1, 77.0], [14.5, 76.7],
  [15.0, 76.9], [15.5, 76.9], [16.0, 77.2], [16.6, 77.4], [17.3, 77.3],
  [17.7, 77.0], [17.8, 76.6], [17.3, 76.2], [17.1, 75.9], [16.6, 75.4],
  [16.3, 75.0], [16.0, 74.8], [15.4, 74.9], [14.8, 74.4], [14.2, 74.4],
  [13.7, 74.5],
];

// Project [lat,lng] into a 0–100 x 0–100 viewBox (y grows south). Pure and
// deterministic so tests can pin the geometry without a DOM.
export function outlinePointsViewBox(outline = KARNATAKA_OUTLINE) {
  const lats = outline.map(p => p[0]);
  const lngs = outline.map(p => p[1]);
  const minLat = Math.min(...lats), maxLat = Math.max(...lats);
  const minLng = Math.min(...lngs), maxLng = Math.max(...lngs);
  return outline
    .map(([lat, lng]) => {
      const x = ((lng - minLng) / (maxLng - minLng)) * 100;
      const y = (1 - (lat - minLat) / (maxLat - minLat)) * 100;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
}

// Map a /saturation/{district}/{crop} response to one radar row, honestly.
// A pair whose fetch failed or whose response carries no numeric percentage
// is flagged `saturationUnavailable` — the view labels it instead of drawing
// a fabricated 0.0%. The intervention thresholds are presentation bands over
// the backend's real figure, unchanged from the original screen.
export function buildRadarRow(q, raw) {
  if (raw === null || raw === undefined) {
    return {
      district: String(q?.district ?? ''), crop: String(q?.crop ?? ''),
      saturation: null, saturationUnavailable: true,
      action: 'Data unavailable', status: 'UNKNOWN',
    };
  }
  const item = raw || {};
  const sat = Number(item.saturation_pct);
  if (!Number.isFinite(sat)) {
    return {
      district: String(item.district ?? q?.district ?? ''),
      crop: String(item.crop ?? q?.crop ?? ''),
      saturation: null, saturationUnavailable: true,
      action: 'Data unavailable', status: 'UNKNOWN',
    };
  }
  // A district with no declarations in any season has not been measured at all.
  // Rendering its 0.0% as "LOW / Maintain Base State" would read as an all-clear
  // issued by the absence of data, so it takes the unavailable path instead.
  if (item.has_declarations === false) {
    return {
      district: String(item.district ?? q?.district ?? ''),
      crop: String(item.crop ?? q?.crop ?? ''),
      saturation: null, saturationUnavailable: true,
      action: 'No sowing declarations', status: 'NO DATA',
      season: item.season ?? null, seasonRequested: item.season_requested ?? null,
    };
  }
  let status = item.risk_level;
  let action = 'Maintain Base State';
  if (sat >= 60.0) { status = 'HIGH'; action = 'CEASE SUBSIDIZED CREDIT'; }
  else if (sat >= 40.0) { status = 'MEDIUM'; action = 'Cap Fertilizer Loans'; }
  else { status = 'LOW'; action = 'Maintain Base State'; }
  return {
    district: String(item.district ?? q?.district ?? ''),
    crop: String(item.crop ?? q?.crop ?? ''),
    saturation: sat,
    saturationUnavailable: false,
    referenceAreaAcres: Number.isFinite(Number(item.reference_area_acres)) ? Number(item.reference_area_acres) : null,
    action,
    status: status || 'LOW',
    // Which season the figure describes: the backend may answer for the latest
    // season that has declarations when the requested one has none, and the
    // reader is entitled to know the number is not from the selected season.
    season: item.season ?? null,
    seasonRequested: item.season_requested ?? null,
    seasonFallback: item.season_fallback === true,
    farmerCount: Number.isFinite(item.farmer_count) ? item.farmer_count : null,
  };
}

// Reactive map source: starts optimistic, degrades on the first tile error,
// and retries when the browser reports the network is back.
export function useMapSource({ theme }) {
  const [tilesFailed, setTilesFailed] = useState(false);
  const [online, setOnline] = useState(typeof navigator === 'undefined' ? true : navigator.onLine);

  useEffect(() => {
    const up = () => { setOnline(true); setTilesFailed(false); };
    const down = () => setOnline(false);
    if (typeof window !== 'undefined') {
      window.addEventListener('online', up);
      window.addEventListener('offline', down);
    }
    return () => {
      if (typeof window !== 'undefined') {
        window.removeEventListener('online', up);
        window.removeEventListener('offline', down);
      }
    };
  }, []);

  const handlers = useMemo(() => ({
    // A whole layer worth of failures is noisy but cheap to observe; Leaflet
    // fires tileerror per tile. One is enough to switch honestly.
    tileerror: () => setTilesFailed(true),
    tileload: (event) => {
      // OSM & other providers edge case: some tile servers return an HTTP 200 OK
      // image with policy blocking or error placeholders (e.g., CartoDB watermark
      // or OSM blocked tiles). Check if the loaded tile element or metadata indicates
      // an error image so we fail closed to the local canvas fallback.
      try {
        const tile = event?.tile;
        if (tile && (tile.naturalWidth === 0 || tile.naturalHeight === 0)) {
          setTilesFailed(true);
          return;
        }
      } catch {
        // Ignore inspection errors
      }
      setTilesFailed(false);
    },
  }), []);

  return {
    source: resolveMapSource({ tilesFailed, online }),
    tileEventHandlers: handlers,
  };
}
