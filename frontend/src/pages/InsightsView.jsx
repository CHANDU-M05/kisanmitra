// src/pages/InsightsView.jsx
import React, { useState, useEffect } from 'react';
import { Shield, Eye, AlertTriangle, MapPin } from 'lucide-react';
import { MapContainer, TileLayer, Marker, Popup, Tooltip as LeafletTooltip, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { API, derive_current_season, get_season_options } from '../config';

export default function InsightsView() {
  const [season, setSeason] = useState(derive_current_season);
  const [allocationData, setAllocationData] = useState([]);
  const [interventionRadar, setInterventionRadar] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filterQuery, setFilterQuery] = useState('');
  const [errorNote, setErrorNote] = useState('');

  const isAdmin = localStorage.getItem('role') === 'admin' && localStorage.getItem('auth_token') !== null;

  const DISTRICT_COORDS = {
    'Bagalkot': [16.1817, 75.6958],
    'Ballari': [15.1394, 76.9214],
    'Belagavi': [15.8497, 74.4977],
    'Bengaluru Rural': [13.2924, 77.5684],
    'Bengaluru Urban': [12.9716, 77.5946],
    'Bidar': [17.9104, 77.5199],
    'Chamarajanagar': [11.9261, 76.9400],
    'Chikkaballapur': [13.4325, 77.7275],
    'Chikkamagaluru': [13.3161, 75.7720],
    'Chitradurga': [14.2251, 76.3980],
    'Dakshina Kannada': [12.8753, 75.0525],
    'Davanagere': [14.4644, 75.9218],
    'Dharwad': [15.4589, 75.0078],
    'Gadag': [15.4300, 75.6320],
    'Hassan': [13.0068, 76.1004],
    'Haveri': [14.7942, 75.4013],
    'Kalaburagi': [17.3297, 76.8343],
    'Kodagu': [12.3375, 75.8069],
    'Kolar': [13.1367, 78.1291],
    'Koppal': [15.3444, 76.1557],
    'Mandya': [12.5218, 76.8951],
    'Mysuru': [12.2958, 76.6394],
    'Raichur': [16.2076, 77.3463],
    'Ramanagara': [12.7150, 77.2813],
    'Shivamogga': [13.9299, 75.5681],
    'Tumakuru': [13.3392, 77.1016],
    'Udupi': [13.3409, 74.7421],
    'Uttara Kannada': [14.8020, 74.8320],
    'Vijayapura': [16.8302, 75.7100],
    'Yadgir': [16.7645, 77.1404],
    'Vijayanagara': [15.2750, 76.3900]
  };

  const getRiskColor = (status) => {
    if (status === 'HIGH') return '#ef4444'; // red-500
    if (status === 'MEDIUM') return '#f59e0b'; // amber-500
    return '#10b981'; // emerald-500
  };

  const createPulseIcon = (color) => {
    return L.divIcon({
      className: 'custom-pulse-wrapper',
      html: `<div class="pulse-marker" style="background-color: ${color};"></div>`,
      iconSize: [24, 24],
      iconAnchor: [12, 12]
    });
  };

  function FitBounds({ positions }) {
    const map = useMap();
    const posString = JSON.stringify(positions); // Use stringify to prevent infinite re-renders on array ref changes
    
    useEffect(() => {
      if (positions && positions.length > 0) {
        const bounds = L.latLngBounds(positions);
        map.fitBounds(bounds, { padding: [50, 50], maxZoom: 8 });
      }
    }, [map, posString]);
    
    return null;
  }

  const getStatusStyle = (status) => {
    switch (status) {
      case 'HIGH':
        return 'bg-red-50 text-red-700 border border-red-200 dark:bg-red-500/10 dark:text-red-400 dark:border-red-500/20';
      case 'MEDIUM':
        return 'bg-amber-50 text-amber-700 border border-amber-200 dark:bg-amber-500/10 dark:text-amber-400 dark:border-amber-500/20';
      case 'LOW':
        return 'bg-emerald-50 text-emerald-700 border border-emerald-250 dark:bg-emerald-500/10 dark:text-emerald-450 dark:border-emerald-500/20';
      default:
        return 'bg-slate-50 text-slate-600 border border-slate-200 dark:bg-white/[0.02] dark:text-slate-400 dark:border-white/5';
    }
  };

  // Robust JSON fetch: per-request timeout (AbortController) + bounded retry
  // with backoff. This is the fix for the "stuck on Ingesting..." symptom:
  // on Render free tier the first request hits a ~40s cold start and can hang
  // or 502. Without a timeout the promise never settles and the spinner is
  // never cleared; the retry rides out the cold start instead of failing.
  const fetchJson = async (url, attempts = 1, timeoutMs = 15000) => {
    let lastErr;
    for (let i = 0; i < attempts; i++) {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), timeoutMs);
      try {
        const res = await fetch(url, { signal: ctrl.signal });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return await res.json();
      } catch (err) {
        lastErr = err;
        if (i < attempts - 1) await new Promise(r => setTimeout(r, 4000));
      } finally {
        clearTimeout(timer);
      }
    }
    throw lastErr;
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErrorNote('');

    fetchJson(`${API}/declarations/summary`, 2)
      .then(summary => {
        if (cancelled) return;

        if (summary && summary.crops) {
          const sortedCrops = Object.entries(summary.crops)
            .map(([name, count]) => ({ name: name.toUpperCase(), value: count }))
            .filter(c => c.value > 0)
            .sort((a, b) => b.value - a.value);

          if (sortedCrops.length > 5) {
            const top5 = sortedCrops.slice(0, 5);
            const othersValue = sortedCrops.slice(5).reduce((sum, item) => sum + item.value, 0);
            if (othersValue > 0) {
              top5.push({ name: 'OTHERS', value: othersValue });
            }
            setAllocationData(top5);
          } else {
            setAllocationData(sortedCrops);
          }
        }

        const fallback = [
          { district: 'Belagavi', crop: 'Maize' },
          { district: 'Chikkaballapur', crop: 'Tomato' },
          { district: 'Belagavi', crop: 'Groundnut' },
          { district: 'Chikkaballapur', crop: 'Ragi' },
          { district: 'Kolar', crop: 'Tomato' }
        ];
        const queries = (summary && Array.isArray(summary.active_pairs) && summary.active_pairs.length > 0)
          ? summary.active_pairs
          : fallback;

        return Promise.all(
          queries.map(q =>
            fetchJson(
              `${API}/saturation/${encodeURIComponent(q.district)}/${encodeURIComponent(q.crop)}?season=${encodeURIComponent(season)}`,
              1
            )
              .catch(err => {
                console.error(`Error loading saturation for ${q.district}/${q.crop}`, err);
                return null; // one bad pair must not sink the whole map
              })
              .then(raw => {
                const item = raw || {};
                const sat = Number(item.saturation_pct ?? 0.0) || 0.0;
                let status = item.risk_level;
                let action = 'Maintain Base State';

                // Active intervention modeling when saturation exceeds simulated 60% threshold
                if (sat >= 60.0) { status = 'HIGH'; action = 'CEASE SUBSIDIZED CREDIT'; }
                else if (sat >= 40.0) { status = 'MEDIUM'; action = 'Cap Fertilizer Loans'; }
                else { status = 'LOW'; action = 'Maintain Base State'; }

                // Coerce identity fields to strings so filteredRadar's
                // .toLowerCase() can never throw on a malformed/missing row.
                return {
                  district: String(item.district ?? q.district ?? ''),
                  crop: String(item.crop ?? q.crop ?? ''),
                  saturation: sat,
                  action: action,
                  status: status || 'LOW'
                };
              })
          )
        );
      })
      .then(radar => {
        if (cancelled) return;
        if (Array.isArray(radar)) setInterventionRadar(radar);
        setLoading(false);
      })
      .catch(err => {
        console.error("Error loading declarations summary", err);
        if (cancelled) return;
        // Critical: clear the spinner even on total backend failure and still
        // render the map (tiles, no markers) behind a non-blocking notice.
        setInterventionRadar([]);
        setErrorNote('Could not reach the live backend \u2014 it may be waking up (free-tier cold start). Showing the map without data; retry in a few seconds.');
        setLoading(false);
      });

    return () => { cancelled = true; };
  }, [season]);

  const filteredRadar = interventionRadar.filter(item => 
    item.district.toLowerCase().includes(filterQuery.toLowerCase()) || 
    item.crop.toLowerCase().includes(filterQuery.toLowerCase())
  );

  return (
    <div className="space-y-6">
      {/* Top filter bar */}
      <div className="bg-white border border-slate-200 rounded-2xl p-5 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 shadow-sm dark:bg-white/5 dark:backdrop-blur-xl dark:border-white/10">
        <div className="space-y-1">
          <h2 className="text-sm font-bold uppercase tracking-wider flex items-center gap-2 text-slate-800 dark:text-white">
            <Shield className="h-4.5 w-4.5 text-emerald-500" /> 
            {isAdmin ? 'Overproduction Intervention Radar' : 'Sowing Saturation Index'}
          </h2>
          <p className="text-xs text-slate-600 dark:text-slate-400">
            {isAdmin 
              ? 'Acreage allocations monitored against critical market saturation thresholds.' 
              : 'ಸೂಕ್ತ ಬಿತ್ತನೆ ಪ್ರಮಾಣ ಸಲಹೆಗಳು ಮತ್ತು ಮಾರುಕಟ್ಟೆ ಸ್ಯಾಚುರೇಶನ್ ಸೂಚ್ಯಂಕ. (Live Kannada crop sowing safety guide)'
            }
          </p>
        </div>
        
        <div className="flex flex-wrap items-center gap-3.5 w-full sm:w-auto font-mono">
          <input
            type="text"
            placeholder="Filter district or crop..."
            value={filterQuery}
            onChange={(e) => setFilterQuery(e.target.value)}
            className="bg-white border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-800 focus:outline-none focus:border-emerald-500 rounded-xl dark:bg-slate-900/60 dark:border-white/10 dark:text-slate-200 w-44"
          />
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-bold text-slate-600 dark:text-slate-400 uppercase tracking-wider">Cycle:</span>
            <select
              value={season}
              onChange={(e) => setSeason(e.target.value)}
              className="bg-white border border-slate-200 px-3 py-1.5 text-xs font-bold text-slate-800 focus:outline-none focus:border-emerald-500 rounded-xl cursor-pointer dark:bg-slate-900/60 dark:border-white/10 dark:text-slate-200"
            >
              {get_season_options().map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
        </div>
      </div>

      {errorNote && (
        <div className="bg-amber-50 border border-amber-200 text-amber-800 dark:bg-amber-500/10 dark:border-amber-500/20 dark:text-amber-400 rounded-xl px-4 py-3 text-xs font-semibold flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span>{errorNote}</span>
        </div>
      )}

      {loading ? (
        <div className="h-64 bg-white border border-slate-200 rounded-2xl flex items-center justify-center text-xs font-bold text-slate-600 animate-pulse shadow-sm dark:bg-white/5 dark:border-white/10 dark:text-slate-450">
          Ingesting Real-time Database Metrics...
        </div>
      ) : (
        /* Main Split Grid */
        <div className="grid grid-cols-1 lg:grid-cols-10 gap-6">
          
          {/* Left: Interactive Map */}
          <div className="lg:col-span-4 bg-white border border-slate-200 rounded-2xl p-0 flex flex-col overflow-hidden h-[360px] shadow-sm dark:bg-slate-900/50 dark:backdrop-blur-xl dark:border-white/10 relative">
            <div className="absolute top-0 left-0 right-0 z-[1000] p-4 bg-gradient-to-b from-white/90 to-transparent dark:from-slate-950/90 pointer-events-none">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-800 dark:text-white flex items-center gap-1.5">
                <MapPin className="h-4 w-4 text-emerald-500" />
                Live Command Map
              </h3>
              <p className="text-[10px] text-slate-600 dark:text-slate-400 mt-1">
                Geospatial saturation density across Karnataka
              </p>
            </div>
            
            <div className="flex-1 w-full h-full z-0 leaflet-container-wrapper">
              <MapContainer 
                center={[14.5, 76.5]} 
                zoom={6} 
                scrollWheelZoom={true}
                className="w-full h-full bg-slate-100 dark:bg-slate-900"
                style={{ background: document.documentElement.classList.contains('dark') ? '#09090b' : '#f4f4f5' }}
              >
                <TileLayer
                  url={document.documentElement.classList.contains('dark')
                    ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
                    : 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png'
                  }
                  attribution='&copy; <a href="https://carto.com/">CartoDB</a>'
                />
                
                <FitBounds 
                  positions={filteredRadar.map(n => DISTRICT_COORDS[n.district]).filter(Boolean)} 
                />
                
                {filteredRadar.map((node, idx) => {
                  const position = DISTRICT_COORDS[node.district];
                  if (!position) return null;
                  
                  return (
                    <Marker 
                      key={idx}
                      position={position} 
                      icon={createPulseIcon(getRiskColor(node.status))}
                    >
                      <LeafletTooltip direction="right" offset={[15, 0]} opacity={1} permanent className="custom-map-tooltip">
                        {node.district}
                      </LeafletTooltip>
                      <Popup className="font-sans text-xs">
                        <div className="font-bold mb-1 uppercase tracking-wider border-b pb-1 text-slate-800">
                          {node.district} Node
                        </div>
                        <div className="space-y-1 mt-2 text-slate-600">
                          <div><span className="font-semibold">Target Crop:</span> {node.crop}</div>
                          <div><span className="font-semibold">Saturation:</span> {node.saturation.toFixed(1)}%</div>
                          <div><span className="font-semibold">Risk Level:</span> <span style={{color: getRiskColor(node.status), fontWeight: 'bold'}}>{node.status}</span></div>
                          <div className="mt-2 pt-2 border-t font-mono text-[9px] font-bold text-slate-500">PROTOCOL: {node.action}</div>
                        </div>
                      </Popup>
                    </Marker>
                  );
                })}
              </MapContainer>
            </div>
            
            {/* Map Legend Overlay */}
            <div className="absolute bottom-4 right-4 z-[1000] bg-white/90 dark:bg-slate-950/90 backdrop-blur border border-slate-200 dark:border-white/10 p-2.5 rounded-xl shadow-lg flex flex-col gap-1.5 text-[9px] font-bold uppercase tracking-wider text-slate-600 dark:text-slate-400">
              <div className="flex items-center gap-2"><div className="w-2.5 h-2.5 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.8)]"></div> OPTIMAL / SAFE</div>
              <div className="flex items-center gap-2"><div className="w-2.5 h-2.5 rounded-full bg-amber-500 shadow-[0_0_8px_rgba(245,158,11,0.8)]"></div> CAUTION / MONITOR</div>
              <div className="flex items-center gap-2"><div className="w-2.5 h-2.5 rounded-full bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.8)]"></div> RISK / CAPPED</div>
            </div>
            
            {/* Global style override to ensure Leaflet popups match our aesthetic if needed, though Tailwind does most of it */}
            <style>{`
              .leaflet-container-wrapper .leaflet-popup-content-wrapper {
                border-radius: 12px;
                box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1);
              }
              html.dark .leaflet-container-wrapper .leaflet-popup-content-wrapper {
                background: #18181b;
                color: #f4f4f5;
              }
              html.dark .leaflet-container-wrapper .leaflet-popup-tip {
                background: #18181b;
              }
              html.dark .leaflet-container-wrapper .leaflet-popup-content .text-slate-800 {
                color: #f4f4f5;
              }
              html.dark .leaflet-container-wrapper .leaflet-popup-content .text-slate-600 {
                color: #a1a1aa;
              }
              html.dark .leaflet-container-wrapper .leaflet-popup-content .border-b,
              html.dark .leaflet-container-wrapper .leaflet-popup-content .border-t {
                border-color: rgba(255,255,255,0.1);
              }

              /* Pulse Marker Animations */
              .custom-pulse-wrapper {
                background: transparent;
                border: none;
              }
              .pulse-marker {
                width: 24px;
                height: 24px;
                border-radius: 50%;
                position: relative;
                display: flex;
                justify-content: center;
                align-items: center;
              }
              .pulse-marker::before {
                content: "";
                position: absolute;
                width: 100%;
                height: 100%;
                border-radius: 50%;
                background: inherit;
                opacity: 0.6;
                animation: pulse-ring 2s cubic-bezier(0.215, 0.61, 0.355, 1) infinite;
              }
              .pulse-marker::after {
                content: "";
                width: 8px;
                height: 8px;
                border-radius: 50%;
                background: white;
                z-index: 2;
                box-shadow: 0 0 4px rgba(0,0,0,0.5);
              }
              @keyframes pulse-ring {
                0% { transform: scale(1); opacity: 0.8; }
                100% { transform: scale(3.5); opacity: 0; }
              }

              /* Permanent Tooltip Styles */
              .leaflet-container-wrapper .custom-map-tooltip {
                background: transparent;
                border: none;
                box-shadow: none;
                font-weight: 900;
                font-size: 10px;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                color: #0f172a;
                text-shadow: 1px 1px 0px rgba(255,255,255,0.9), -1px -1px 0px rgba(255,255,255,0.9), 1px -1px 0px rgba(255,255,255,0.9), -1px 1px 0px rgba(255,255,255,0.9);
              }
              html.dark .leaflet-container-wrapper .custom-map-tooltip {
                color: #f8fafc;
                text-shadow: 1px 1px 0px rgba(0,0,0,0.9), -1px -1px 0px rgba(0,0,0,0.9), 1px -1px 0px rgba(0,0,0,0.9), -1px 1px 0px rgba(0,0,0,0.9);
              }
              .leaflet-container-wrapper .custom-map-tooltip::before {
                display: none;
              }
            `}</style>
          </div>

          {/* Right: Intervention Table */}
          <div className="lg:col-span-6 bg-white border border-slate-200 rounded-2xl p-5 flex flex-col justify-between h-[360px] shadow-sm dark:bg-white/5 dark:backdrop-blur-xl dark:border-white/10">
            <div>
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-800 dark:text-white flex items-center gap-1.5 border-b border-slate-100 dark:border-white/5 pb-3 mb-3">
                {isAdmin ? 'Intervention Protocol Registry' : 'District Sowing Capacity Guide'}
              </h3>
            </div>
            
            <div className="flex-1 overflow-x-auto">
              <table className="min-w-[500px] lg:w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="border-b border-slate-150 dark:border-white/5 bg-slate-50/55 dark:bg-slate-950/20 font-bold uppercase text-[9px] text-slate-700 dark:text-slate-400 tracking-wider">
                    <th className="p-3">District</th>
                    <th className="p-3">Primary Crop</th>
                    <th className="p-3 text-right">Saturation Limit</th>
                    <th className="p-3 text-right">{isAdmin ? 'Action Protocol' : 'Sowing Safety Status'}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-white/5 text-slate-700 dark:text-slate-350">
                  {filteredRadar.map((row, idx) => (
                    <tr key={idx} className="hover:bg-slate-50/55 dark:hover:bg-white/[0.02] transition-colors">
                      <td className="p-3 font-bold text-slate-900 dark:text-white">{row.district}</td>
                      <td className="p-3 font-semibold text-slate-800 dark:text-slate-400">{row.crop}</td>
                      <td className="p-3 text-right font-mono font-bold">
                        <span className={`inline-block px-2.5 py-0.5 text-[10px] font-bold rounded ${getStatusStyle(row.status)}`}>
                          {row.saturation.toFixed(2)}%
                        </span>
                      </td>
                      <td className="p-3 text-right font-bold flex items-center justify-end gap-1.5">
                        {isAdmin ? (
                          <>
                            {row.status === 'HIGH' && <AlertTriangle className="h-3.5 w-3.5 text-red-500 shrink-0" />}
                            <span className={row.action === 'CEASE SUBSIDIZED CREDIT' ? "text-red-600 dark:text-red-400 animate-pulse font-black" : "text-slate-700 dark:text-slate-350"}>
                              {row.action}
                            </span>
                          </>
                        ) : (
                          <>
                            {row.status === 'HIGH' && (
                              <span className="text-red-500 bg-red-500/10 border border-red-500/20 px-2 py-0.5 rounded text-[10px] uppercase font-mono tracking-wider animate-pulse">
                                🚨 ಅಧಿಕ ಪ್ರಮಾಣ (CEASE SUBSIDIZED CREDIT / Risk)
                              </span>
                            )}
                            {row.status === 'MEDIUM' && (
                              <span className="text-amber-500 bg-amber-500/10 border border-amber-500/20 px-2 py-0.5 rounded text-[10px] uppercase font-mono tracking-wider">
                                ಮಧ್ಯಮ ಪ್ರಮಾಣ (Caution / Monitor)
                              </span>
                            )}
                            {row.status === 'LOW' && (
                              <span className="text-emerald-500 bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 rounded text-[10px] uppercase font-mono tracking-wider">
                                ಸೂಕ್ತ ಪ್ರಮಾಣ (Optimal / Safe)
                              </span>
                            )}
                          </>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="bg-slate-50 border-t border-slate-150 dark:bg-white/[0.02] dark:border-white/5 p-3 text-[10px] font-mono font-bold text-slate-600 flex items-center gap-2 rounded-b-xl mt-4">
              <Eye className="h-3.5 w-3.5" />
              <span>
                {isAdmin 
                  ? 'METRICS SYNCED DIRECTLY WITH KARNATAKA SURVEY RECORDS.' 
                  : 'ಕೃಷಿ ಇಲಾಖೆ ಹಾಗೂ ಉಪಗ್ರಹ ಮಾಹಿತಿ ಆಧಾರಿತ ಲೈವ್ ಇಂಡೆಕ್ಸ್ (Live Sat Satellite Index)'
                }
              </span>
            </div>
          </div>

        </div>
      )}
    </div>
  );
}
