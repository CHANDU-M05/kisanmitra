// src/pages/TerminalView.jsx
import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { ResponsiveContainer, ComposedChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ReferenceLine, Customized } from 'recharts';
import { ShieldAlert, TrendingDown, Thermometer, HelpCircle, Layers, CheckCircle2, Info, FlaskConical } from 'lucide-react';

import Card from '../components/ui/Card';
import { fetchJson, apiUrl } from '../api';
import {
  buildChartData,
  deriveForecastView,
  feedBanner,
  latestHistoricalPrice,
} from '../forecastState';

// ---- Reliability / simulation theme, single source of truth ----------
// Thresholds live here ONCE. Previously duplicated in the Row 3 tier badge
// with its own copy of the 15/25 cutoffs — that's how they drift apart.
const RELIABILITY_TIERS = [
  { max: 15, label: 'HIGH RELIABILITY',     color: '#10b981', gradient: ['#10b981', '#059669'], dash: '0',
    badge: 'bg-emerald-50 text-emerald-700 border border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/20' },
  { max: 25, label: 'MODERATE RELIABILITY', color: '#f59e0b', gradient: ['#f59e0b', '#10b981'], dash: '4 4',
    badge: 'bg-amber-50 text-amber-700 border border-amber-200 dark:bg-amber-500/10 dark:text-amber-400 dark:border-amber-500/20' },
  { max: Infinity, label: 'LOW RELIABILITY', color: '#dc2626', gradient: ['#dc2626', '#f59e0b'], dash: '6 6',
    badge: 'bg-red-50 text-red-700 border border-red-200 dark:bg-red-500/10 dark:text-red-400 dark:border-red-500/20' },
];

const SIMULATION_THEME = {
  color: '#d97706', gradient: ['#d97706', '#f59e0b'], dash: '3 3',
  badge: 'bg-amber-50 text-amber-700 border border-amber-200 dark:bg-amber-500/10 dark:text-amber-400 dark:border-amber-500/20',
};

// No forecast means no measured accuracy either. Claiming "HIGH RELIABILITY" for
// a market we cannot price is exactly the kind of confident-but-wrong display
// this screen used to produce, so accuracy-less states get their own label.
const UNKNOWN_THEME = {
  color: '#64748b', gradient: ['#64748b', '#94a3b8'], dash: '2 4', label: 'NO ACCURACY DATA',
  badge: 'bg-slate-100 text-slate-600 border border-slate-300 dark:bg-slate-500/10 dark:text-slate-400 dark:border-slate-500/20',
};

// ── Confidence band: drawn as a proper SVG polygon via Recharts Customized ──
// Uses xAxisMap/yAxisMap (documented Recharts API) to compute pixel coordinates
// directly from data values — does NOT depend on formattedGraphicalItems.
const ConfidenceBandLayer = React.memo(function ConfidenceBandLayer(props) {
  const { xAxisMap, yAxisMap, themeColor, chartData } = props;

  try {
    // Recharts stores axes as objects keyed by axis ID (usually 0)
    const xAxis = xAxisMap && (xAxisMap[0] ?? Object.values(xAxisMap)[0]);
    const yAxis = yAxisMap && (yAxisMap[0] ?? Object.values(yAxisMap)[0]);
    if (!xAxis?.scale || !yAxis?.scale || !chartData?.length) return null;

    const xScale  = xAxis.scale;
    const yScale  = yAxis.scale;
    // Ordinal/band scales have bandwidth; point scales and linear scales don't
    const xOffset = typeof xScale.bandwidth === 'function' ? xScale.bandwidth() / 2 : 0;

    // Only forecast data points carry confidence bounds
    const pts = chartData.filter(
      d => d.confidenceHigh != null && d.confidenceLow != null
    );
    if (pts.length < 2) return null;

    const upper = pts
      .map(d => ({ x: xScale(d.day) + xOffset, y: yScale(d.confidenceHigh) }))
      .filter(p => Number.isFinite(p.x) && Number.isFinite(p.y));
    const lower = pts
      .map(d => ({ x: xScale(d.day) + xOffset, y: yScale(d.confidenceLow) }))
      .filter(p => Number.isFinite(p.x) && Number.isFinite(p.y));

    if (upper.length < 2 || lower.length < 2) return null;

    const upperPath = upper.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x},${p.y}`).join(' ');
    const lowerPath = [...lower].reverse().map(p => `L${p.x},${p.y}`).join(' ');
    const bandPath  = `${upperPath} ${lowerPath} Z`;
    const pts2str   = arr => arr.map(p => `${p.x},${p.y}`).join(' ');

    // Gradient bounds in real pixel coordinates (gradientUnits="userSpaceOnUse")
    const gx1 = upper[0].x;
    const gx2 = upper[upper.length - 1].x;
    const gy1 = Math.min(...upper.map(p => p.y));
    const gy2 = Math.max(...lower.map(p => p.y));

    return (
      <g>
        <defs>
          {/* Horizontal gradient — fades in from the junction, fans toward T+60 */}
          <linearGradient id="cbGradH" gradientUnits="userSpaceOnUse" x1={gx1} y1="0" x2={gx2} y2="0">
            <stop offset="0%"   stopColor={themeColor} stopOpacity={0.0} />
            <stop offset="12%"  stopColor={themeColor} stopOpacity={0.12} />
            <stop offset="75%"  stopColor={themeColor} stopOpacity={0.18} />
            <stop offset="100%" stopColor={themeColor} stopOpacity={0.07} />
          </linearGradient>
          {/* Vertical gradient — edge highlight gives band a glassy depth */}
          <linearGradient id="cbGradV" gradientUnits="userSpaceOnUse" x1="0" y1={gy1} x2="0" y2={gy2}>
            <stop offset="0%"   stopColor={themeColor} stopOpacity={0.25} />
            <stop offset="25%"  stopColor={themeColor} stopOpacity={0.05} />
            <stop offset="75%"  stopColor={themeColor} stopOpacity={0.05} />
            <stop offset="100%" stopColor={themeColor} stopOpacity={0.25} />
          </linearGradient>
        </defs>

        {/* Main horizontal fill */}
        <path d={bandPath} fill={`url(#cbGradH)`} />
        {/* Vertical depth layer */}
        <path d={bandPath} fill={`url(#cbGradV)`} opacity={0.55} />

        {/* Upper dashed boundary */}
        <polyline
          points={pts2str(upper)} fill="none"
          stroke={themeColor} strokeWidth={1.2}
          strokeDasharray="3 5" strokeOpacity={0.5} strokeLinecap="round"
        />
        {/* Lower dashed boundary */}
        <polyline
          points={pts2str(lower)} fill="none"
          stroke={themeColor} strokeWidth={1.2}
          strokeDasharray="3 5" strokeOpacity={0.5} strokeLinecap="round"
        />
      </g>
    );
  } catch {
    return null; // Degrade gracefully if coordinate system isn't ready yet
  }
});

function getTheme(mapePct, isSimulated) {
  if (isSimulated) return SIMULATION_THEME;
  if (mapePct == null) return { ...UNKNOWN_THEME };
  const tier = RELIABILITY_TIERS.find(t => mapePct < t.max) ?? RELIABILITY_TIERS[RELIABILITY_TIERS.length - 1];
  return { ...tier };
}

function getReliabilityLabel(mapePct) {
  if (mapePct == null) return UNKNOWN_THEME.label;
  const tier = RELIABILITY_TIERS.find(t => mapePct < t.max) ?? RELIABILITY_TIERS[RELIABILITY_TIERS.length - 1];
  return tier.label;
}

const formatINR = (value) => (value == null ? '—' : `₹${Math.round(value).toLocaleString('en-IN')}`);

function getEnvLabel(val) {
  if (val < -15) return 'Severe Drought';
  if (val < 0) return 'Mild Dryness';
  if (val === 0) return 'Normal Baseline';
  if (val < 15) return 'Mild Wetness';
  return 'Excess Rainfall';
}

export default function TerminalView() {
  const [selectedCrop, setSelectedCrop] = useState('Tomato');
  const [selectedMarket, setSelectedMarket] = useState('Kolar');
  const [cropsList, setCropsList] = useState(['Tomato', 'Maize', 'Onion', 'Potato', 'Ragi']);
  const [marketsList, setMarketsList] = useState(['Kolar', 'Belagavi', 'Chikkaballapur', 'Dharwad', 'Mysuru']);


  // One object describes what the server actually returned. Every
  // forecast-derived number below is read from it, so a stale or missing market
  // cannot leave a previous crop's prediction on screen or render a null as ₹0.
  const [forecastView, setForecastView] = useState(deriveForecastView(null));

  const [envDeviation, setEnvDeviation] = useState(0);
  const [subsidyLevel, setSubsidyLevel] = useState('Normalized');

  const [historicalData, setHistoricalData] = useState([]);

  // Backend-supplied, never a local constant: `total` is the reference acreage
  // the saturation percentage was measured against, and is null until loaded.
  const [capacity, setCapacity] = useState({ filled: null, total: null, percentage: null, basis: null });
  const [computedData, setComputedData] = useState([]);

  const trend = forecastView.trend;
  const anomalyMeta = forecastView.anomaly;
  const cropMeta = forecastView.cropMeta;
  const forecastPricePoint = forecastView.predicted;
  const forecastTarget = forecastView.predicted;
  const confidenceHigh = forecastView.high;
  const confidenceLow = forecastView.low;

  const isAdmin = localStorage.getItem('role') === 'admin' && localStorage.getItem('auth_token') !== null;

  useEffect(() => {
    fetchJson(apiUrl('/prices/crops-markets'), { attempts: 2 })
      .then(data => {
        if (data.crops && data.crops.length > 0) {
          setCropsList(data.crops);
        }
        if (data.markets && data.markets.length > 0) {
          setMarketsList(data.markets);
        }
      })
      .catch(err => console.error("Error fetching crops-markets stats on mount", err));
  }, []);

  useEffect(() => {
    let cancelled = false;
    // The cancelled flag previously had NO cleanup hook, so switching markets
    // never cancelled the old chain: a slow response for the PREVIOUS
    // selection could still setState and overwrite the current chart.
    // Now unmount/selection-change aborts in-flight requests outright.
    const ctrl = new AbortController();
    // Reset first: a stale or empty market must never keep showing the previous
    // selection's prediction while the new request is in flight.
    setForecastView({ ...deriveForecastView(null), state: 'loading' });

    fetchJson(apiUrl(`/prices/history/${encodeURIComponent(selectedMarket)}/${encodeURIComponent(selectedCrop)}`), { signal: ctrl.signal })
      .then(history => {
        if (cancelled) return;
        if (!Array.isArray(history) || history.length === 0) {
          // The endpoint used to answer "no rows" with a fabricated seasonal
          // series and the dashboard read its last point as today's price. An
          // empty array now means exactly what it says: nothing recorded.
          setHistoricalData([]);
          setForecastView(deriveForecastView({ type: 'no_data', crop: selectedCrop, market: selectedMarket }));
          return;
        }
        setHistoricalData(history);
        // No current_price and no arrivals_tonnes in the URL: the backend
        // resolves the verified mandi price itself and refuses it if too old.
        return fetchJson(apiUrl(`/prices/predict?commodity=${encodeURIComponent(selectedCrop)}&market=${encodeURIComponent(selectedMarket)}`), { signal: ctrl.signal })
          .then(pred => { if (!cancelled) setForecastView(deriveForecastView(pred)); });
      })
      .catch(err => {
        if (cancelled) return;
        console.error("Error loading historical prices", err);
        setForecastView(deriveForecastView(null));
      });

    fetchJson(apiUrl(`/saturation/${encodeURIComponent(selectedMarket)}/${encodeURIComponent(selectedCrop)}`), { signal: ctrl.signal })
      .then(data => {
        // The backend already computed saturation against a documented reference
        // area. Dividing by a hardcoded 175 here produced a second, invented
        // percentage that matched nothing the bot or API reported.
        setCapacity({
          filled: Number.isFinite(data.total_area) ? data.total_area : null,
          total: Number.isFinite(data.reference_area_acres) ? data.reference_area_acres : null,
          percentage: Number.isFinite(data.saturation_pct) ? Math.round(data.saturation_pct) : null,
          basis: data.reference_basis ?? null,
        });
      })
      .catch(err => {
        if (cancelled) return;
        console.error("Error loading saturation metrics", err);
        setCapacity({ filled: null, total: null, percentage: null, basis: null });
      });

    return () => { cancelled = true; ctrl.abort(); };
  }, [selectedCrop, selectedMarket]);

  useEffect(() => {
    // The projected spline is drawn only when a real forecast exists; history
    // alone is still shown, because observed prices remain true when they age.
    setComputedData(buildChartData(historicalData, forecastView, { envDeviation, subsidyLevel }));
  }, [envDeviation, subsidyLevel, historicalData, forecastView]);

  const lastHistoricalPrice = latestHistoricalPrice(historicalData);
  const dynamicT60Price = computedData.find(item => item.day === 'T+60')?.forecast ?? forecastPricePoint;
  const dynamicNetShift = (dynamicT60Price != null && lastHistoricalPrice != null)
    ? dynamicT60Price - lastHistoricalPrice
    : null;
  const isSimulated = envDeviation !== 0 || subsidyLevel !== 'Normalized';

  // Fixed: was checking 'Inflationary', which the <select> never actually emits
  // ('Inflation' does) — this branch was unreachable dead code before.
  const scenarioName = useMemo(() => {
    if (envDeviation < 0) return 'Drought';
    if (envDeviation > 0) return 'Rainfall Spike';
    if (subsidyLevel === 'Inflation') return 'Inflationary Vector';
    if (subsidyLevel === 'Relief') return 'Fiscal Relief Vector';
    return 'Simulation';
  }, [envDeviation, subsidyLevel]);

  const theme = useMemo(
    () => getTheme(cropMeta.crop_mape_pct, isSimulated),
    [cropMeta.crop_mape_pct, isSimulated]
  );

  const banner = useMemo(() => {
    const b = feedBanner(forecastView, {
      crop: selectedCrop, market: selectedMarket, isSimulated, scenarioName,
    });
    switch (b.tone) {
      case 'unavailable':
        return { ...b, container: 'bg-slate-100 text-slate-700 border border-slate-300 dark:bg-slate-500/10 dark:text-slate-300 dark:border-slate-500/20', icon: <Info className="h-4 w-4 shrink-0" /> };
      case 'muted':
        return { ...b, container: 'bg-slate-50 text-slate-500 border border-slate-200 dark:bg-slate-500/10 dark:text-slate-400 dark:border-slate-500/20', icon: <Info className="h-4 w-4 shrink-0" /> };
      case 'scenario':
        return { ...b, container: 'bg-amber-50 text-amber-700 border border-amber-200 dark:bg-amber-500/10 dark:text-amber-400 dark:border-amber-500/20', icon: <FlaskConical className="h-4 w-4 shrink-0" /> };
      case 'BEARISH':
        return { ...b, container: 'bg-red-50 text-red-700 border border-red-200 dark:bg-red-500/10 dark:text-red-400 dark:border-red-500/20', icon: <ShieldAlert className="h-4 w-4 shrink-0" /> };
      case 'BULLISH':
        return { ...b, container: 'bg-emerald-50 text-emerald-700 border border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-450 dark:border-emerald-500/20', icon: <CheckCircle2 className="h-4 w-4 shrink-0" /> };
      default:
        return { ...b, container: 'bg-amber-50 text-amber-700 border border-amber-200 dark:bg-amber-500/10 dark:text-amber-400 dark:border-amber-500/20', icon: <Info className="h-4 w-4 shrink-0" /> };
    }
  }, [forecastView, isSimulated, scenarioName, selectedCrop, selectedMarket]);

  // Stable component ref for Recharts Customized \u2014 recreated only when
  // computedData or theme changes to avoid stale closure over chart data.
  const bandComponent = useCallback(
    (props) => <ConfidenceBandLayer {...props} themeColor={theme.color} chartData={computedData} />,
    [computedData, theme.color]
  );

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-lg font-black uppercase tracking-wider text-slate-900 dark:text-white">
          Market Prices &amp; Forecasts
        </h1>
        {isSimulated && (
          <span className="text-[9px] font-black px-2.5 py-1 rounded-full bg-blue-50 text-blue-700 border border-blue-200 dark:bg-blue-500/10 dark:text-blue-400 dark:border-blue-500/20 animate-pulse uppercase tracking-wider">
            🚨 [SIMULATED SCENARIO ACTIVE]
          </span>
        )}
      </div>

      {(anomalyMeta.is_anomaly || Math.abs(envDeviation) >= 30) && forecastView.hasForecast && (
        <div className="bg-amber-500/10 border border-amber-500/30 text-amber-800 dark:text-amber-300 px-4 py-3 rounded-2xl flex items-center justify-between shadow-sm animate-fade-in">
          <div className="flex items-center gap-2.5 text-xs font-bold font-mono">
            <ShieldAlert className="w-4 h-4 text-amber-600 dark:text-amber-400 shrink-0" />
            <span>
              ⚠️ ANOMALY ALERT ({selectedCrop}): {anomalyMeta.deviation_pct || Math.abs(envDeviation)}% Price Deviation Detected ({anomalyMeta.anomaly_type || 'SHIFT'}).
            </span>
          </div>
          <span className="text-[9px] font-bold uppercase tracking-wider px-2 py-1 rounded bg-amber-500/20 text-amber-900 dark:text-amber-200 border border-amber-500/30">
            Human-in-the-Loop Validation Active
          </span>
        </div>
      )}

      {/* Control deck */}
      <Card className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-bold text-slate-700 dark:text-slate-400 uppercase tracking-widest">Crop:</span>
            <select value={selectedCrop} onChange={(e) => setSelectedCrop(e.target.value)}
              className="bg-white border border-slate-200 px-3 py-1.5 text-xs font-bold text-slate-800 focus:outline-none focus:border-emerald-500 rounded-xl cursor-pointer dark:bg-slate-900/60 dark:border-white/10 dark:text-slate-200">
              {cropsList.map(c => <option key={c} value={c}>{c.toUpperCase()}</option>)}
            </select>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-[10px] font-bold text-slate-700 dark:text-slate-400 uppercase tracking-widest">Market:</span>
            <select value={selectedMarket} onChange={(e) => setSelectedMarket(e.target.value)}
              className="bg-white border border-slate-200 px-3 py-1.5 text-xs font-bold text-slate-800 focus:outline-none focus:border-emerald-500 rounded-xl cursor-pointer dark:bg-slate-900/60 dark:border-white/10 dark:text-slate-200">
              {marketsList.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>

          <div className="flex items-center gap-2">
            <TrendingDown className={`h-4 w-4 ${trend === 'BEARISH' ? 'text-red-500' : 'text-emerald-500'}`} />
            <span className="text-xs font-bold text-slate-700 dark:text-slate-400 uppercase tracking-wider">Model:</span>
            <span className={`text-xs font-mono font-bold uppercase tracking-wider ${
              trend === 'BEARISH' ? 'text-red-600 dark:text-red-400' : trend === 'BULLISH' ? 'text-emerald-600 dark:text-emerald-500' : 'text-amber-650 dark:text-amber-400'
            }`}>{trend} SIGNAL</span>
          </div>
        </div>

        <div className={`text-xs font-bold px-4 py-3 flex items-center gap-2.5 rounded-xl uppercase tracking-wider border ${banner.container}`}>
          {banner.icon}
          <span>{banner.text}</span>
        </div>
      </Card>

      {/* Grid canvas */}
      <div className="grid grid-cols-1 lg:grid-cols-10 gap-6">
        <Card className={`${isAdmin ? 'lg:col-span-7' : 'lg:col-span-10'} flex flex-col h-[440px]`}>
          <div className="flex justify-between items-center border-b border-slate-100 dark:border-white/5 pb-3 mb-2">
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-800 dark:text-white flex items-center gap-1.5">
              <Layers className="h-4 w-4 text-emerald-500" /> Live Mandi Spline Forecast &amp; Risk Bounds
            </h3>
            <div className="flex items-center gap-2">
              {isSimulated && (
                <span className="text-[9px] font-mono font-bold text-amber-700 border border-amber-200 px-2.5 py-0.5 bg-amber-50 rounded dark:bg-amber-500/10 dark:text-amber-400 dark:border-amber-500/20">
                  SIMULATION ACTIVE
                </span>
              )}
              <span className="text-[9px] font-mono font-bold text-emerald-600 border border-emerald-200 px-2 py-0.5 bg-emerald-50 rounded dark:bg-emerald-500/10 dark:border-emerald-500/20 dark:text-emerald-500">
                ML Engine
              </span>
            </div>
          </div>

          {/* Chart Legend */}
          <div className="flex items-center gap-5 mb-2 flex-wrap">
            <div className="flex items-center gap-2">
              <svg width="20" height="8">
                <line x1="0" y1="4" x2="20" y2="4" stroke="#3b82f6" strokeWidth="2.5" strokeLinecap="round" />
                <circle cx="10" cy="4" r="2.5" fill="#3b82f6" />
              </svg>
              <span className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">Historical Spot</span>
            </div>
            <div className="flex items-center gap-2">
              <svg width="20" height="8">
                <line x1="0" y1="4" x2="20" y2="4" stroke={theme.color} strokeWidth="2.5" strokeDasharray="4 3" strokeLinecap="round" />
              </svg>
              <span className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">ML Prediction</span>
            </div>
            <div className="flex items-center gap-2">
              <svg width="20" height="10">
                <rect x="0" y="1" width="20" height="8" rx="2" fill={theme.color} opacity="0.22" />
                <line x1="0" y1="1" x2="20" y2="1" stroke={theme.color} strokeWidth="1" strokeDasharray="3 4" strokeOpacity="0.5" />
                <line x1="0" y1="9" x2="20" y2="9" stroke={theme.color} strokeWidth="1" strokeDasharray="3 4" strokeOpacity="0.5" />
              </svg>
              <span className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">15–85th Percentile Band</span>
            </div>
          </div>

          {/* Provenance strip: what the numbers on this chart actually are. The
              forecast is shown only when the server produced one, and the record
              date is always visible so an old price cannot read as a new one. */}
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mb-2 text-[9px] font-mono font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
            <span>
              Latest record:{' '}
              {forecastView.provenance?.price_as_of ?? 'UNAVAILABLE'}
              {forecastView.provenance?.days_old != null ? ` (${forecastView.provenance.days_old}d old)` : ''}
            </span>
            <span>Mandi: {forecastView.provenance?.source_market ?? selectedMarket}</span>
            <span>
              Arrivals:{' '}
              {forecastView.provenance?.arrivals_provenance === 'recorded'
                ? `${Number(forecastView.provenance?.arrivals_tonnes ?? 0).toLocaleString('en-IN')} t`
                : (forecastView.provenance?.arrivals_provenance ?? 'unknown').replace('_', ' ')}
            </span>
            {forecastView.state === 'stale' && (
              <span className="text-red-600 dark:text-red-400">
                Stale — no forecast ({(forecastView.provenance?.stale_reason ?? 'unknown').replace(/_/g, ' ')})
              </span>
            )}
            {(forecastView.provenance?.data_quality ?? []).map(flag => (
              <span key={flag} className="text-amber-700 dark:text-amber-400">⚠ {flag.replace(/_/g, ' ')}</span>
            ))}
          </div>

          <div className="flex-1 w-full font-mono text-[10px]" style={{height: 'calc(100% - 60px)'}}>
            {computedData.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center gap-2 text-center px-6">
                <span className="text-[11px] font-bold uppercase tracking-widest text-slate-600 dark:text-slate-300">
                  No verified records for {selectedCrop} in {selectedMarket}
                </span>
                <span className="text-[10px] leading-relaxed text-slate-500 dark:text-slate-400 max-w-sm">
                  The chart and forecast stay empty instead of showing estimated prices.
                  Real rows appear here as soon as the AGMARKNET feed carries this market.
                </span>
              </div>
            ) : (
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={computedData} margin={{ top: 12, right: 16, left: -25, bottom: 0 }}>
                <defs />

                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(100,116,139,0.12)" />
                <XAxis dataKey="day" stroke="#94a3b8" axisLine={false} tickLine={false} tick={{ fontSize: 9, fontFamily: 'monospace', fontWeight: 600 }} />
                <YAxis stroke="#94a3b8" axisLine={false} tickLine={false} domain={['dataMin - 200', 'dataMax + 200']} tick={{ fontSize: 9, fontFamily: 'monospace' }} />

                <Tooltip
                  contentStyle={{ backgroundColor: 'rgba(15,23,42,0.92)', border: '1px solid rgba(255,255,255,0.08)', color: '#e2e8f0', borderRadius: '12px', boxShadow: '0 20px 40px -8px rgba(0,0,0,0.4)', fontSize: 11, backdropFilter: 'blur(12px)' }}
                  labelStyle={{ fontWeight: 800, fontFamily: 'monospace', color: '#f8fafc', marginBottom: 6, fontSize: 12 }}
                  itemStyle={{ fontFamily: 'monospace', padding: '1px 0' }}
                  cursor={{ stroke: 'rgba(148,163,184,0.3)', strokeWidth: 1, strokeDasharray: '4 4' }}
                  formatter={(value, name) => {
                    if (value === null || value === undefined) return [null, null];
                    const meta = {
                      historical: { label: 'Historical Spot Price',   color: '#60a5fa' },
                      forecast:   { label: 'ML Prediction (T+60)',    color: theme.color },
                    };
                    const { label, color } = meta[name] ?? { label: null, color: '#fff' };
                    if (!label) return [null, null]; // hide unlabelled series
                    return [<span style={{ color, fontWeight: 700 }}>{`₹${Math.round(value).toLocaleString('en-IN')}`}</span>, label];
                  }}
                />

                {/* T+60 reference line — only when a forecast exists, otherwise
                    this would draw a line at ₹0 across real history. */}
                {forecastTarget != null && (
                <ReferenceLine
                  y={forecastTarget}
                  stroke={theme.color}
                  strokeDasharray="4 4"
                  strokeOpacity={0.6}
                  strokeWidth={1}
                  label={{
                    value: `T+60 · ₹${Math.round(forecastTarget).toLocaleString('en-IN')}`,
                    fill: theme.color, position: 'insideTopRight',
                    fontSize: 9, fontWeight: 800, fontFamily: 'monospace',
                  }}
                />
                )}

                {/* ── Confidence band — stable ref, dark+light safe ── */}
                <Customized component={bandComponent} />

                {/* ── Historical line ── */}
                <Line
                  type="monotone" dataKey="historical" name="historical"
                  stroke="#3b82f6" strokeWidth={2.5}
                  dot={{ r: 3, fill: '#3b82f6', strokeWidth: 0 }}
                  activeDot={{ r: 6, fill: '#3b82f6', stroke: 'rgba(59,130,246,0.3)', strokeWidth: 4 }}
                  connectNulls
                />

                {/* ── Forecast line: wide blurred glow layer + crisp top layer ── */}
                {/* The glow layer uses name="" so Recharts excludes it from tooltip */}
                <Line
                  type="monotone" dataKey="forecast" name=""
                  stroke={theme.color} strokeWidth={6}
                  strokeDasharray={theme.dash} strokeOpacity={0.15}
                  dot={false} activeDot={false} connectNulls legendType="none"
                />
                <Line
                  type="monotone" dataKey="forecast" name="forecast"
                  stroke={theme.color} strokeWidth={2.5}
                  strokeDasharray={theme.dash}
                  dot={{ r: 4, fill: theme.color, strokeWidth: 2, stroke: 'rgba(255,255,255,0.6)' }}
                  activeDot={{ r: 6, fill: theme.color, stroke: 'rgba(255,255,255,0.3)', strokeWidth: 3 }}
                  connectNulls
                />
              </ComposedChart>
            </ResponsiveContainer>
            )}
          </div>
        </Card>

        {isAdmin && (
          <Card className="lg:col-span-3 flex flex-col justify-between">
            <div className="space-y-5">
              <div className="border-b border-slate-100 dark:border-white/5 pb-3">
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-900 dark:text-white flex items-center gap-1.5">
                  <Thermometer className="h-4 w-4 text-red-500" /> Scenario Sandbox
                </h3>
                <p className="text-[11px] text-slate-600 dark:text-slate-500 mt-1.5 leading-relaxed">
                  Adjust environment variables to test price movements on the forecasting spline.
                </p>
              </div>

              <div className="space-y-2">
                <div className="flex justify-between items-center text-xs font-bold">
                  <span className="flex items-center gap-1 text-slate-600 dark:text-slate-300">Environmental Shift <HelpCircle className="h-3 w-3 text-slate-400" /></span>
                  <span className="font-mono text-red-600 bg-red-50 border border-red-200 dark:bg-red-500/10 dark:text-red-400 dark:border-red-500/20 px-2 py-0.5 text-[10px] rounded">
                    {envDeviation > 0 ? '+' : ''}{envDeviation}%
                  </span>
                </div>
                <input type="range" min="-30" max="30" value={envDeviation}
                  onChange={(e) => setEnvDeviation(parseInt(e.target.value))}
                  className="w-full accent-slate-800 dark:accent-emerald-500 bg-slate-100 dark:bg-slate-800 h-1 rounded-lg cursor-pointer" />
                <div className="flex justify-between text-[9px] font-bold text-slate-400 dark:text-slate-500 font-mono">
                  <span>DROUGHT</span>
                  <span className="text-slate-800 dark:text-slate-300 uppercase font-bold">{getEnvLabel(envDeviation)}</span>
                  <span>WET</span>
                </div>
              </div>

              <div className="space-y-2">
                <label className="text-xs font-bold block text-slate-600 dark:text-slate-300">Fiscal Policy Vector</label>
                <select value={subsidyLevel} onChange={(e) => setSubsidyLevel(e.target.value)}
                  className="w-full bg-white border border-slate-200 p-2.5 text-xs font-bold text-slate-800 focus:outline-none focus:border-slate-400 rounded-xl cursor-pointer dark:bg-slate-900/60 dark:border-white/10 dark:text-slate-200">
                  <option value="Normalized">Baseline Production Costing</option>
                  <option value="Inflation">12% Fuel/Fertilizer Inflation Hike</option>
                  <option value="Relief">8% Support Relief Subsidy</option>
                </select>
              </div>
            </div>

            <button onClick={() => { setEnvDeviation(0); setSubsidyLevel('Normalized'); }}
              className="w-full bg-slate-900 text-white hover:bg-slate-800 dark:bg-emerald-500 dark:text-slate-950 dark:hover:bg-emerald-600 text-xs font-bold py-3 mt-6 transition-all rounded-xl uppercase tracking-wider shadow-sm">
              Reset Simulation State
            </button>
          </Card>
        )}
      </div>

      {/* Bottom widgets */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card className="space-y-4">
          <div className="flex justify-between items-center">
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-400">Declared Acreage vs Reference Area</h4>
            <span className="font-mono text-[10px] font-bold bg-emerald-50 text-emerald-600 border border-emerald-250 dark:bg-emerald-500/10 dark:border-emerald-500/20 dark:text-emerald-500 px-2 py-0.5 rounded">
              {capacity.percentage == null ? '—% Saturated' : `${capacity.percentage}% Saturated`}
            </span>
          </div>
          <div className="space-y-2">
            <div className="flex justify-between text-xs font-bold">
              <span className="text-slate-800 dark:text-slate-300">{selectedMarket} declarations</span>
              <span className="font-mono text-slate-600 dark:text-slate-500">
                {capacity.filled == null ? '—' : capacity.filled.toFixed(1)}
                {' / '}
                {capacity.total == null ? 'no reference' : capacity.total.toFixed(1)}
                {' Acres'}
              </span>
            </div>
            <div className="w-full h-3 bg-slate-100 border border-slate-200 dark:bg-slate-950/20 dark:border-white/5 rounded-lg overflow-hidden">
              <div className="h-full bg-gradient-to-r from-emerald-500 to-teal-500 transition-all duration-500" style={{ width: `${capacity.percentage == null ? 0 : Math.max(capacity.percentage, 2)}%` }} />
            </div>
            {capacity.basis === 'state_average_fallback' && (
              <p className="text-[9px] font-mono text-amber-600 dark:text-amber-400 uppercase tracking-wider">
                Reference is a state average — no district/crop figure on record
              </p>
            )}
          </div>
        </Card>

        <Card className="flex flex-col justify-center">
          <div className="flex justify-between items-center mb-3">
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-400">Real-time Matrix Readout</h4>
            {isSimulated && <span className="text-[9px] font-mono font-black text-amber-600 dark:text-amber-400 tracking-wider">[SIMULATED]</span>}
          </div>

          <div className="grid grid-cols-2 divide-x divide-slate-200 dark:divide-white/5 font-mono mb-4">
            <div className="pr-5 flex flex-col">
              <span className="text-[10px] font-bold text-slate-600 dark:text-slate-400 uppercase tracking-widest mb-1">T+60 Projected Spot</span>
              <span className="text-2xl font-black text-slate-950 dark:text-white">{formatINR(dynamicT60Price)}</span>
            </div>
            <div className="pl-5 flex flex-col">
              <span className="text-[10px] font-bold text-slate-600 dark:text-slate-400 uppercase tracking-widest mb-1">Net Structural Shift</span>
              <span className={`text-2xl font-black ${dynamicNetShift == null
                ? 'text-slate-400 dark:text-slate-500'
                : dynamicNetShift < 0 ? 'text-red-500' : 'text-emerald-500'}`}>
                {dynamicNetShift == null ? '—' : `${dynamicNetShift > 0 ? '+' : ''}${formatINR(dynamicNetShift)}`}
              </span>
            </div>
          </div>

          <div className="border-t border-slate-100 dark:border-white/5 pt-3 mb-3">
            <span className="text-[10px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-widest block mb-1">15–85th Percentile Band</span>
            {confidenceLow != null && confidenceHigh != null ? (
            <div className="flex items-center gap-2 font-mono">
              <span className="text-sm font-bold text-slate-700 dark:text-slate-300">{formatINR(confidenceLow)}</span>
              <div className="flex-1 h-1.5 rounded-full bg-slate-100 dark:bg-white/10 relative">
                <div className="absolute inset-y-0 rounded-full" style={{ left: '10%', right: '10%', background: `linear-gradient(90deg, ${theme.gradient[0]}, ${theme.gradient[1]})` }} />
              </div>
              <span className="text-sm font-bold text-slate-700 dark:text-slate-300">{formatINR(confidenceHigh)}</span>
            </div>
            ) : (
              <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500">
                No band — no forecast for this market right now
              </span>
            )}
          </div>

          {/* Reliability badge now reuses the SAME theme object as the chart —
              no second copy of the 15/25 MAPE thresholds to fall out of sync. */}
          {cropMeta.crop_mape_pct !== null && (
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-widest">Model Accuracy ({selectedCrop})</span>
              <span className={`text-[10px] font-black px-2 py-0.5 rounded border font-mono ${theme.badge}`}>
                {cropMeta.crop_mape_pct.toFixed(1)}% MAPE · {getReliabilityLabel(cropMeta.crop_mape_pct)}
              </span>
            </div>
          )}
          {cropMeta.crop_mape_pct === null && forecastView.hasForecast === false && (
            <div className="text-[10px] font-mono font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500">
              Model accuracy hidden — nothing was forecast
            </div>
          )}

          {cropMeta.msp_floor !== null && (
            <div className="mt-2 flex items-center justify-between border-t border-slate-100 dark:border-white/5 pt-2">
              <span className="text-[10px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-widest">MSP Floor (2025-26)</span>
              <div className="flex items-center gap-1.5 font-mono">
                <span className="text-[10px] font-bold text-slate-700 dark:text-slate-300">{formatINR(cropMeta.msp_floor)}</span>
                {cropMeta.msp_ratio !== null && (
                  <span className={`text-[9px] font-black px-1.5 py-0.5 rounded border ${
                    cropMeta.msp_ratio >= 1.0
                      ? 'text-emerald-700 bg-emerald-50 border-emerald-250 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/20'
                      : 'text-red-700 bg-red-50 border-red-200 dark:bg-red-500/10 dark:text-red-400 dark:border-red-500/20'
                  }`}>
                    {cropMeta.msp_ratio >= 1.0 ? `+${((cropMeta.msp_ratio - 1) * 100).toFixed(0)}% ABOVE` : `${((1 - cropMeta.msp_ratio) * 100).toFixed(0)}% BELOW`}
                  </span>
                )}
              </div>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
