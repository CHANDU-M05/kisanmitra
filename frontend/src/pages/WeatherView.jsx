// src/pages/WeatherView.jsx
import React, { useState, useEffect } from 'react';
import { CloudRain, Sun, Wind, Thermometer, Droplets, CheckCircle, ShieldAlert, AlertTriangle } from 'lucide-react';
import Card from '../components/ui/Card';
import { fetchJson } from '../api';

// Canonical district-HQ coordinates for all 31 Karnataka districts.
// Source: same authoritative values used by InsightsView (Wikipedia district HQ).
// Used to query Open-Meteo (free, no key, CORS-enabled) for real weather.
const DISTRICT_COORDS = {
  Bagalkot: [16.1817, 75.6958],
  Ballari: [15.1394, 76.9214],
  Belagavi: [15.8497, 74.4977],
  'Bengaluru Rural': [13.2924, 77.5684],
  'Bengaluru Urban': [12.9716, 77.5946],
  Bidar: [17.9104, 77.5199],
  Chamarajanagar: [11.9261, 76.9400],
  Chikkaballapur: [13.4325, 77.7275],
  Chikkamagaluru: [13.3161, 75.7720],
  Chitradurga: [14.2251, 76.3980],
  'Dakshina Kannada': [12.8753, 75.0525],
  Davanagere: [14.4644, 75.9218],
  Dharwad: [15.4589, 75.0078],
  Gadag: [15.4300, 75.6320],
  Hassan: [13.0068, 76.1004],
  Haveri: [14.7942, 75.4013],
  Kalaburagi: [17.3297, 76.8343],
  Kodagu: [12.3375, 75.8069],
  Kolar: [13.1367, 78.1291],
  Koppal: [15.3444, 76.1557],
  Mandya: [12.5218, 76.8951],
  Mysuru: [12.2958, 76.6394],
  Raichur: [16.2076, 77.3463],
  Ramanagara: [12.7150, 77.2813],
  Shivamogga: [13.9299, 75.5681],
  Tumakuru: [13.3392, 77.1016],
  Udupi: [13.3409, 74.7421],
  'Uttara Kannada': [14.8020, 74.8320],
  Vijayapura: [16.8302, 75.7100],
  Yadgir: [16.7645, 77.1404],
  Vijayanagara: [15.2750, 76.3900],
};

const KARNATAKA_DISTRICTS = Object.keys(DISTRICT_COORDS).sort();

// Open-Meteo: free, no API key, CORS-enabled. Returns current real weather.
function weatherUrl(lat, lng) {
  return `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lng}&current=temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m&hourly=precipitation_probability&forecast_days=1`;
}

// Derive agronomic advisories from REAL conditions, not fabricated seeds.
function deriveAdvisories(conditions) {
  const { temp, humidity, rainProb, precipitation } = conditions;
  const crops = ['Tomato', 'Maize', 'Ragi', 'Onion', 'Potato', 'Groundnut'];
  const advisories = [];

  for (const crop of crops.slice(0, 3)) {
    let status, note;
    if (rainProb > 70 || precipitation > 10) {
      status = 'RISK';
      note = `Heavy rainfall expected (${rainProb}% probability). Ensure drainage for ${crop}; delay transplanting until water recedes.`;
    } else if (temp > 38) {
      status = 'RISK';
      note = `Extreme heat (${temp}°C). Provide shade/mulch for ${crop}; increase irrigation frequency.`;
    } else if (temp >= 18 && temp <= 32 && humidity >= 50 && humidity <= 85) {
      status = 'OPTIMAL';
      note = `Favorable conditions (${temp}°C, ${humidity}% humidity) for ${crop}. Sowing and transplanting window is open.`;
    } else if (humidity < 40) {
      status = 'WARNING';
      note = `Low humidity (${humidity}%). Monitor soil moisture closely for ${crop}; pre-irrigate before sowing.`;
    } else {
      status = 'WARNING';
      note = `Moderate conditions for ${crop}. Track weather updates; ensure adequate moisture before transplanting.`;
    }
    const color = status === 'OPTIMAL'
      ? 'text-emerald-700 bg-emerald-50 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/20'
      : status === 'WARNING'
        ? 'text-amber-700 bg-amber-50 border-amber-200 dark:bg-amber-500/10 dark:text-amber-400 dark:border-amber-500/20'
        : 'text-red-700 bg-red-50 border-red-200 dark:bg-red-500/10 dark:text-red-400 dark:border-red-500/20';
    advisories.push({ crop, status, note, color });
  }
  return advisories;
}

export default function WeatherView() {
  const [selectedDistrict, setSelectedDistrict] = useState('Kolar');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const coords = DISTRICT_COORDS[selectedDistrict];
    if (!coords) {
      setError('District not found in weather database.');
      setLoading(false);
      return;
    }
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);

    fetchJson(weatherUrl(coords[0], coords[1]), { signal: ctrl.signal, timeoutMs: 12000 })
      .then(raw => {
        const cur = raw.current;
        // Precipitation probability: take the max across today's remaining hours
        const hourly = raw.hourly?.precipitation_probability || [];
        const rainProb = hourly.length > 0 ? Math.max(...hourly) : 0;
        const conditions = {
          temp: Math.round(cur.temperature_2m),
          humidity: cur.relative_humidity_2m,
          rainChance: rainProb,
          precipitation: cur.precipitation ?? 0,
          windSpeed: cur.wind_speed_10m,
          weatherCode: cur.weather_code,
        };
        setData({
          ...conditions,
          soilMoisture: conditions.precipitation > 5 ? 'High' : conditions.precipitation > 1 ? 'Medium' : conditions.humidity > 60 ? 'Medium' : 'Low',
          advisories: deriveAdvisories(conditions),
          updatedAt: cur.time,
        });
        setLoading(false);
      })
      .catch(err => {
        if (err.name === 'AbortError') return;
        setError('Weather data temporarily unavailable. Check your connection.');
        setLoading(false);
      });
    return () => { ctrl.abort(); };
  }, [selectedDistrict]);

  const getStatusIcon = (status) => {
    switch (status) {
      case 'OPTIMAL':
        return <CheckCircle className="h-4 w-4 shrink-0" />;
      case 'WARNING':
        return <AlertTriangle className="h-4 w-4 shrink-0" />;
      default:
        return <ShieldAlert className="h-4 w-4 shrink-0" />;
    }
  };

  return (
    <div className="space-y-6">
      {/* Top Banner Control deck */}
      <Card className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div className="space-y-1">
          <h2 className="text-sm font-bold uppercase tracking-wider flex items-center gap-2 text-slate-900 dark:text-white">
            <CloudRain className="h-4 w-4 text-emerald-500" /> Climate &amp; Sowing Window Forecast
          </h2>
          <p className="text-xs text-slate-600 dark:text-slate-400">
            Real-time weather from Open-Meteo for {selectedDistrict}.
            {data?.updatedAt ? ` Observed: ${data.updatedAt}` : ''}
          </p>
        </div>

        <div className="flex items-center gap-2 self-stretch sm:self-auto font-mono">
          <span className="text-[10px] font-bold text-slate-700 uppercase tracking-wider">Select District:</span>
          <select
            value={selectedDistrict}
            onChange={(e) => setSelectedDistrict(e.target.value)}
            className="bg-white border border-slate-200 px-3 py-1.5 text-xs font-bold text-slate-800 focus:outline-none focus:border-slate-400 rounded-xl cursor-pointer dark:bg-slate-900/60 dark:border-white/10 dark:text-slate-200"
          >
            {KARNATAKA_DISTRICTS.map(d => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
        </div>
      </Card>

      {/* Loading state */}
      {loading && (
        <div className="flex items-center justify-center py-16" role="status">
          <div className="animate-spin h-8 w-8 border-4 border-emerald-500 border-t-transparent rounded-full" />
          <span className="ml-3 text-xs font-bold text-slate-600 dark:text-slate-400 uppercase tracking-wider">Fetching weather for {selectedDistrict}…</span>
        </div>
      )}

      {/* Error state */}
      {error && !loading && (
        <div className="bg-red-50 border border-red-200 text-red-700 dark:bg-red-500/10 dark:border-red-500/30 dark:text-red-400 rounded-xl px-4 py-3 text-xs font-bold flex items-center gap-2">
          <ShieldAlert className="h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Climate parameters grid — real data */}
      {!loading && !error && data && (
        <>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-6">

          {/* Param 1 */}
          <Card className="flex items-center gap-4">
            <div className="h-10 w-10 bg-orange-50 text-orange-600 dark:bg-orange-500/10 dark:text-orange-400 rounded-xl flex items-center justify-center font-bold">
              <Thermometer className="h-5 w-5" />
            </div>
            <div className="flex flex-col">
              <span className="text-[10px] font-bold text-slate-700 dark:text-slate-400 uppercase tracking-widest">Temperature</span>
              <span className="text-2xl font-black text-orange-600">{data.temp}°C</span>
            </div>
          </Card>

          {/* Param 2 */}
          <Card className="flex items-center gap-4">
            <div className="h-10 w-10 bg-blue-50 text-blue-600 dark:bg-blue-500/10 dark:text-blue-400 rounded-xl flex items-center justify-center font-bold">
              <Droplets className="h-5 w-5" />
            </div>
            <div className="flex flex-col">
              <span className="text-[10px] font-bold text-slate-700 dark:text-slate-400 uppercase tracking-widest">Humidity</span>
              <span className="text-2xl font-black text-blue-600">{data.humidity}%</span>
            </div>
          </Card>

          {/* Param 3 */}
          <Card className="flex items-center gap-4">
            <div className="h-10 w-10 bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-400 rounded-xl flex items-center justify-center font-bold">
              <CloudRain className="h-5 w-5" />
            </div>
            <div className="flex flex-col">
              <span className="text-[10px] font-bold text-slate-700 dark:text-slate-400 uppercase tracking-widest">Rain Probability</span>
              <span className="text-2xl font-black text-indigo-600">{data.rainChance}%</span>
            </div>
          </Card>

          {/* Param 4 */}
          <Card className="flex items-center gap-4">
            <div className="h-10 w-10 bg-teal-50 text-teal-600 dark:bg-teal-500/10 dark:text-teal-400 rounded-xl flex items-center justify-center font-bold">
              <Wind className="h-5 w-5" />
            </div>
            <div className="flex flex-col">
              <span className="text-[10px] font-bold text-slate-700 dark:text-slate-400 uppercase tracking-widest">Wind Speed</span>
              <span className="text-2xl font-black text-teal-600">{data.windSpeed?.toFixed(0) ?? '—'} km/h</span>
            </div>
          </Card>

        </div>

        {/* Advisories derived from real conditions */}
        <Card className="space-y-4">
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-900 dark:text-white flex items-center gap-1.5 border-b border-slate-100 dark:border-white/5 pb-3">
            Sowing Window &amp; Crop Recommendations for {selectedDistrict}
          </h3>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {data.advisories.map((adv, idx) => (
              <div key={idx} className="border border-slate-200 dark:border-white/10 dark:bg-white/[0.02] rounded-2xl p-5 flex flex-col justify-between space-y-4 hover:shadow-md transition-shadow">
                <div className="flex justify-between items-center">
                  <span className="text-sm font-black text-slate-950 dark:text-white uppercase tracking-wider">{adv.crop}</span>
                  <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-xl text-[10px] font-bold uppercase border ${adv.color}`}>
                    {getStatusIcon(adv.status)}
                    <span>{adv.status}</span>
                  </span>
                </div>
                <p className="text-xs text-slate-700 dark:text-slate-400 leading-relaxed font-sans font-medium">
                  {adv.note}
                </p>
              </div>
            ))}
          </div>
        </Card>
        </>
      )}
    </div>
  );
}
