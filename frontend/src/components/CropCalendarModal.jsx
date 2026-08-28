// src/components/CropCalendarModal.jsx
import React from 'react';
import { X, Calendar, Info, CheckCircle2, AlertCircle } from 'lucide-react';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

const CROP_CALENDAR_DATA = [
  {
    crop: 'Tomato',
    type: 'Perishable Vegetable',
    bestSowing: ['Jun', 'Jul', 'Oct', 'Nov'],
    harvesting: ['Aug', 'Sep', 'Dec', 'Jan'],
    season: 'Kharif / Late Rabi',
    notes: 'Avoid peak monsoon planting (Jul-Aug in heavy rain zones) to prevent blight.',
    color: 'emerald',
  },
  {
    crop: 'Maize',
    type: 'Cereal / Grain',
    bestSowing: ['May', 'Jun', 'Oct'],
    harvesting: ['Sep', 'Oct', 'Feb'],
    season: 'Kharif / Rabi',
    notes: 'Kharif sowing aligned with early monsoon yields highest kernel density in Karnataka.',
    color: 'amber',
  },
  {
    crop: 'Onion',
    type: 'Commercial Bulb',
    bestSowing: ['May', 'Jun', 'Oct', 'Nov'],
    harvesting: ['Sep', 'Oct', 'Feb', 'Mar'],
    season: 'Kharif / Late Kharif / Rabi',
    notes: 'Store harvested Kharif onions carefully due to moisture sensitivity.',
    color: 'purple',
  },
  {
    crop: 'Potato',
    type: 'Tuber',
    bestSowing: ['May', 'Jun', 'Oct'],
    harvesting: ['Aug', 'Sep', 'Jan'],
    season: 'Kharif / Rabi',
    notes: 'Hassan and Kolar districts peak sowing starts with early Kharif showers.',
    color: 'orange',
  },
  {
    crop: 'Ragi (Finger Millet)',
    type: 'Staple Millet',
    bestSowing: ['Jul', 'Aug'],
    harvesting: ['Nov', 'Dec'],
    season: 'Main Kharif',
    notes: 'Highly drought-resilient. Ideal for rainfed southern Karnataka districts.',
    color: 'amber',
  },
  {
    crop: 'Brinjal',
    type: 'Horticulture',
    bestSowing: ['Jun', 'Jul', 'Nov', 'Dec'],
    harvesting: ['Sep', 'Oct', 'Feb', 'Mar'],
    season: 'Year-round / Kharif-Rabi',
    notes: 'Requires moderate irrigation during flowering stage.',
    color: 'violet',
  },
];

export default function CropCalendarModal({ isOpen, onClose }) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/70 backdrop-blur-sm animate-fade-in">
      <div 
        className="relative w-full max-w-4xl max-h-[90vh] bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-2xl overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/50">
          <div className="flex items-center gap-3">
            <div className="p-2.5 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 rounded-xl border border-emerald-500/20">
              <Calendar className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base font-bold text-slate-900 dark:text-white uppercase tracking-wider">
                Karnataka Crop Sowing Calendar
              </h2>
              <p className="text-xs text-slate-500 dark:text-slate-400 font-mono">
                Agronomic Sowing & Harvesting Windows by Commodity
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-slate-400 hover:text-slate-700 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800 rounded-xl transition-all"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Legend */}
        <div className="px-5 py-3 bg-slate-50 dark:bg-slate-950/60 border-b border-slate-100 dark:border-slate-800 flex items-center gap-6 text-xs font-bold font-mono">
          <div className="flex items-center gap-2">
            <span className="w-3 h-3 rounded-md bg-emerald-500/80 border border-emerald-600"></span>
            <span className="text-slate-700 dark:text-slate-300">Optimal Sowing Window</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-3 h-3 rounded-md bg-blue-500/40 border border-blue-500"></span>
            <span className="text-slate-700 dark:text-slate-300">Harvesting Phase</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-3 h-3 rounded-md bg-slate-200 dark:bg-slate-800 border border-slate-300 dark:border-slate-700"></span>
            <span className="text-slate-400">Off-Season / Maintenance</span>
          </div>
        </div>

        {/* Calendar Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse min-w-[700px]">
              <thead>
                <tr className="border-b border-slate-200 dark:border-slate-800">
                  <th className="pb-3 text-xs font-bold text-slate-400 uppercase tracking-wider w-44">Crop & Type</th>
                  {MONTHS.map(m => (
                    <th key={m} className="pb-3 text-center text-xs font-bold font-mono text-slate-500 dark:text-slate-400 uppercase">
                      {m}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60 font-mono text-xs">
                {CROP_CALENDAR_DATA.map((item) => (
                  <tr key={item.crop} className="hover:bg-slate-50/50 dark:hover:bg-slate-800/30 transition-colors">
                    <td className="py-3.5 pr-3 font-sans">
                      <div className="font-bold text-slate-900 dark:text-white flex items-center gap-1.5">
                        {item.crop}
                      </div>
                      <div className="text-[10px] text-slate-500 dark:text-slate-400 font-mono">
                        {item.season}
                      </div>
                    </td>
                    {MONTHS.map(m => {
                      const isSowing = item.bestSowing.includes(m);
                      const isHarvest = item.harvesting.includes(m);
                      return (
                        <td key={m} className="py-3.5 px-1 text-center">
                          {isSowing ? (
                            <span 
                              className="inline-block w-full py-1.5 rounded-md bg-emerald-500/20 text-emerald-700 dark:text-emerald-400 font-bold border border-emerald-500/40 text-[10px]"
                              title={`${item.crop}: Best Sowing Month (${m})`}
                            >
                              SOW
                            </span>
                          ) : isHarvest ? (
                            <span 
                              className="inline-block w-full py-1.5 rounded-md bg-blue-500/15 text-blue-700 dark:text-blue-400 font-bold border border-blue-500/30 text-[10px]"
                              title={`${item.crop}: Harvesting Month (${m})`}
                            >
                              HARV
                            </span>
                          ) : (
                            <span className="inline-block w-full py-1.5 text-slate-300 dark:text-slate-700 text-[10px]">
                              -
                            </span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Agronomic tips footer note */}
          <div className="mt-4 p-4 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-start gap-3">
            <Info className="w-4 h-4 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
            <div className="text-xs text-amber-800 dark:text-amber-300 leading-relaxed font-sans">
              <span className="font-bold uppercase tracking-wider block mb-0.5 font-mono text-[10px]">Sowing Window Recommendation:</span>
              Staggering crop sowing dates across adjacent taluks reduces localized mandi saturation by up to 34%. Combine this crop calendar with live saturation levels before finalizing acreage allocations.
            </div>
          </div>
        </div>

        {/* Footer actions */}
        <div className="p-4 border-t border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/50 flex justify-end">
          <button
            onClick={onClose}
            className="px-5 py-2 bg-slate-900 text-white dark:bg-emerald-500 dark:text-slate-950 hover:bg-slate-800 dark:hover:bg-emerald-400 rounded-xl font-bold text-xs uppercase tracking-wider transition-all"
          >
            Close Calendar
          </button>
        </div>
      </div>
    </div>
  );
}
