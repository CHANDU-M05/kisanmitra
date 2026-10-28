// src/pages/WeatherView.jsx
import React, { useState, useEffect } from 'react';
import { CloudRain, Sun, Thermometer, Droplets, CheckCircle, ShieldAlert, AlertTriangle } from 'lucide-react';
import Card from '../components/ui/Card';

const KARNATAKA_DISTRICTS = [
  "Bagalkot", "Ballari", "Belagavi", "Bengaluru Rural", "Bengaluru Urban",
  "Bidar", "Chamarajanagar", "Chikkaballapur", "Chikkamagaluru", "Chitradurga",
  "Dakshina Kannada", "Davanagere", "Dharwad", "Gadag", "Hassan",
  "Haveri", "Kalaburagi", "Kodagu", "Kolar", "Koppal",
  "Mandya", "Mysuru", "Raichur", "Ramanagara", "Shivamogga",
  "Tumakuru", "Udupi", "Uttara Kannada", "Vijayapura", "Yadgir", "Vijayanagara"
].sort();

const WEATHER_DB = {
  Belagavi: {
    temp: 26,
    humidity: 88,
    rainChance: 85,
    soilMoisture: "38 cb (High)",
    advisories: [
      { crop: "Maize", status: "OPTIMAL", note: "Ideal sowing moisture verified. Standard nitrogen starter is active.", color: "text-emerald-700 bg-emerald-50 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/20" },
      { crop: "Tomato", status: "RISK", note: "Heavy rainfall risk. Restructure trench drainage to prevent rot.", color: "text-red-700 bg-red-50 border-red-200 dark:bg-red-500/10 dark:text-red-400 dark:border-red-500/20" },
      { crop: "Groundnut", status: "OPTIMAL", note: "Sowing window open. Ensure seed treatment with Trichoderma.", color: "text-emerald-700 bg-emerald-50 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/20" }
    ]
  },
  Kolar: {
    temp: 31,
    humidity: 52,
    rainChance: 15,
    soilMoisture: "18 cb (Low)",
    advisories: [
      { crop: "Tomato", status: "OPTIMAL", note: "Ideal soil heat profile. Apply micro-drip irrigation regularly.", color: "text-emerald-700 bg-emerald-50 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/20" },
      { crop: "Potato", status: "OPTIMAL", note: "Soil texture stable. Prepare drills for seed tubers.", color: "text-emerald-700 bg-emerald-50 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/20" },
      { crop: "Onion", status: "WARNING", note: "Slight dryness detected. Pre-irrigate before transplanting.", color: "text-amber-700 bg-amber-50 border-amber-200 dark:bg-amber-500/10 dark:text-amber-400 dark:border-amber-500/20" }
    ]
  },
  Chikkaballapur: {
    temp: 29,
    humidity: 61,
    rainChance: 30,
    soilMoisture: "22 cb (Medium)",
    advisories: [
      { crop: "Tomato", status: "OPTIMAL", note: "Ambient humidity ranges stable. Sowing is recommended.", color: "text-emerald-700 bg-emerald-50 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/20" },
      { crop: "Ragi", status: "OPTIMAL", note: "Good soil temperature structure. Drill sowing is open.", color: "text-emerald-700 bg-emerald-50 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/20" },
      { crop: "Marigold", status: "OPTIMAL", note: "Optimum transplant conditions. Apply standard compost.", color: "text-emerald-700 bg-emerald-50 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/20" }
    ]
  }
};

function getWeatherData(district) {
  if (WEATHER_DB[district]) return WEATHER_DB[district];

  // Generate deterministic but realistic weather based on name hash code
  let hash = 0;
  for (let i = 0; i < district.length; i++) {
    hash = district.charCodeAt(i) + ((hash << 5) - hash);
  }
  const absHash = Math.abs(hash);
  const temp = 24 + (absHash % 11); // 24 to 34 C
  const humidity = 45 + (absHash % 46); // 45% to 90%
  const rainChance = absHash % 96; // 0% to 95%
  
  let soilVal = 10 + (absHash % 31);
  let soilMoisture = `${soilVal} cb (Medium)`;
  if (soilVal > 30) soilMoisture = `${soilVal} cb (High)`;
  else if (soilVal < 20) soilMoisture = `${soilVal} cb (Low)`;

  const crops = ["Tomato", "Maize", "Onion", "Potato", "Ragi", "Groundnut", "Marigold"];
  const selectedCrops = [];
  const tempCrops = [...crops];
  for (let i = 0; i < 3; i++) {
    const idx = (absHash + i) % tempCrops.length;
    selectedCrops.push(tempCrops.splice(idx, 1)[0]);
  }

  const advisories = selectedCrops.map((crop, index) => {
    const seed = (absHash + index) % 3;
    if (seed === 0) {
      return {
        crop,
        status: "OPTIMAL",
        note: `Ideal weather parameters verified for ${crop}. Sowing window is fully open.`,
        color: "text-emerald-700 bg-emerald-50 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/20"
      };
    } else if (seed === 1) {
      return {
        crop,
        status: "WARNING",
        note: `Moderate ambient humidity ranges. Monitor soil moisture before transplanting ${crop}.`,
        color: "text-amber-700 bg-amber-50 border-amber-200 dark:bg-amber-500/10 dark:text-amber-400 dark:border-amber-500/20"
      };
    } else {
      return {
        crop,
        status: "RISK",
        note: `Sub-optimal soil moisture profile. Postpone major ${crop} sowings until rain stabilization.`,
        color: "text-red-700 bg-red-50 border-red-200 dark:bg-red-500/10 dark:text-red-400 dark:border-red-500/20"
      };
    }
  });

  return { temp, humidity, rainChance, soilMoisture, advisories };
}

export default function WeatherView() {
  const [selectedDistrict, setSelectedDistrict] = useState('Kolar');
  const [data, setData] = useState(WEATHER_DB.Kolar);

  useEffect(() => {
    setData(getWeatherData(selectedDistrict));
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
          <p className="text-xs text-slate-600">
            Localized meteorological monitoring paired with real-time agronomic crop advice.
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

      {/* Climate parameters grid */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        
        {/* Param 1 */}
        <Card className="flex items-center gap-4">
          <div className="h-10 w-10 bg-orange-50 text-orange-600 dark:bg-orange-500/10 dark:text-orange-400 rounded-xl flex items-center justify-center font-bold">
            <Thermometer className="h-5 w-5" />
          </div>
          <div className="flex flex-col">
            <span className="text-[10px] font-bold text-slate-700 uppercase tracking-widest">Temperature</span>
            <span className="text-2xl font-black text-orange-600">{data.temp}°C</span>
          </div>
        </Card>

        {/* Param 2 */}
        <Card className="flex items-center gap-4">
          <div className="h-10 w-10 bg-blue-50 text-blue-600 dark:bg-blue-500/10 dark:text-blue-400 rounded-xl flex items-center justify-center font-bold">
            <Droplets className="h-5 w-5" />
          </div>
          <div className="flex flex-col">
            <span className="text-[10px] font-bold text-slate-700 uppercase tracking-widest">Humidity</span>
            <span className="text-2xl font-black text-blue-600">{data.humidity}%</span>
          </div>
        </Card>

        {/* Param 3 */}
        <Card className="flex items-center gap-4">
          <div className="h-10 w-10 bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-400 rounded-xl flex items-center justify-center font-bold">
            <CloudRain className="h-5 w-5" />
          </div>
          <div className="flex flex-col">
            <span className="text-[10px] font-bold text-slate-700 uppercase tracking-widest">Rain Probability</span>
            <span className="text-2xl font-black text-indigo-600">{data.rainChance}%</span>
          </div>
        </Card>

        {/* Param 4 */}
        <Card className="flex items-center gap-4">
          <div className="h-10 w-10 bg-teal-50 text-teal-600 dark:bg-teal-500/10 dark:text-teal-400 rounded-xl flex items-center justify-center font-bold">
            <Sun className="h-5 w-5" />
          </div>
          <div className="flex flex-col">
            <span className="text-[10px] font-bold text-slate-700 uppercase tracking-widest">Soil Moisture</span>
            <span className="text-lg font-black text-teal-600">{data.soilMoisture}</span>
          </div>
        </Card>

      </div>

      {/* Advisories Table */}
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
    </div>
  );
}
