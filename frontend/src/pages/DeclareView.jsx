// src/pages/DeclareView.jsx
import React, { useState, useEffect } from 'react';
import { ClipboardCheck, ShieldAlert, Sparkles, Send, ArrowRight } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { useTranslation } from 'react-i18next';
import { derive_current_season, get_season_options } from '../config';
import { cachedGet, postJson, apiUrl } from '../api';

export default function DeclareView() {
  const [districts, setDistricts] = useState([]);
  const [crops, setCrops] = useState([]);
  const [form, setForm] = useState({
    farmerName: '',
    phone: '',
    village: '',
    district: 'Kolar',
    crop: 'Tomato',
    areaAcres: '',
    season: derive_current_season()
  });
  
  const [loading, setLoading] = useState(false);
  const [receipt, setReceipt] = useState(null);
  const { t } = useTranslation();

  // Load lookup lists on mount — through the shared summary cache (Layout
  // fetches the same payload) with timeout+retry, so a cold-start hang can
  // never leave the selects empty longer than the timeout window.
  useEffect(() => {
    const ctrl = new AbortController();
    cachedGet(apiUrl('/declarations/summary'), { attempts: 2, signal: ctrl.signal })
      .then(data => {
        if (data.districts) setDistricts(data.districts);
        if (data.crops) setCrops(Object.keys(data.crops));
      })
      .catch(err => {
        console.error("Error loading registry summary dynamic options", err);
        // Fallbacks keep the form fully usable if the backend is unavailable.
        setDistricts(["Kolar", "Belagavi", "Chikkaballapur", "Davanagere", "Tumakuru"]);
        setCrops(["Tomato", "Onion", "Potato", "Ragi", "Maize"]);
      });
    return () => ctrl.abort();
  }, []);

  const handleChange = (e) => {
    const { name, value } = e.target;
    setForm(prev => ({ ...prev, [name]: value }));
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    setReceipt(null);

    // Form valid check
    if (form.phone.trim().length !== 10 || isNaN(form.phone.trim())) {
      toast.error('Please input a valid 10-digit mobile number.');
      return;
    }

    const acres = parseFloat(form.areaAcres);
    if (isNaN(acres) || acres <= 0) {
      toast.error('Please enter a valid acreage (> 0).');
      return;
    }

    setLoading(true);

    // Writes NEVER auto-retry (postJson is timeout-only): a duplicate
    // declaration attempt must be a conscious user action, not a silent
    // background resend. setLoading always settles in the finally below.
    (async () => {
      try {
        const { ok, status, data } = await postJson(apiUrl('/farmer/declare'), {
          farmer_name: form.farmerName.trim(),
          phone: form.phone.trim(),
          village: form.village.trim(),
          district: form.district,
          crop: form.crop,
          area_acres: acres,
          season: form.season
        });
        if (!ok) throw new Error(`Could not process crop registry. (HTTP ${status})`);
        setReceipt({
          id: data.declaration_id,
          reply: data.whatsapp_reply,
          saturation: data.saturation
        });
        setForm(prev => ({
          ...prev,
          farmerName: '',
          phone: '',
          village: '',
          areaAcres: ''
        }));
        toast.success('Crop declaration submitted successfully!');
      } catch (err) {
        console.error("Post crop declaration failed", err);
        toast.error("Could not save the declaration — the server was unreachable or rejected it. Please try again.");
      } finally {
        setLoading(false);
      }
    })();
  };

  return (
    <div className="space-y-6">
      {/* Top Banner Control deck */}
      <div className="bg-white border border-slate-200 rounded-2xl p-5 flex flex-col md:flex-row justify-between items-start md:items-center gap-4 shadow-sm dark:bg-white/5 dark:backdrop-blur-xl dark:border-white/10">
        <div className="space-y-1">
          <h2 className="text-sm font-bold uppercase tracking-wider flex items-center gap-2 text-slate-950 dark:text-white">
            <ClipboardCheck className="h-4.5 w-4.5 text-emerald-500" /> {t('declare.title')}
          </h2>
          <p className="text-xs text-slate-600 dark:text-slate-400">
            {t('declare.subtitle')}
          </p>
        </div>
      </div>

      {/* Main split grid */}
      <div className="grid grid-cols-1 lg:grid-cols-10 gap-6">
        
        {/* Left: Registration console Form (4 col) */}
        <div className="lg:col-span-4 bg-white border border-slate-200 rounded-2xl p-5 flex flex-col justify-between shadow-sm min-h-[400px] dark:bg-white/5 dark:backdrop-blur-xl dark:border-white/10">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="border-b border-slate-100 dark:border-white/5 pb-3 mb-2">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-900 dark:text-white">
                Sowing Declaration Form
              </h3>
            </div>

            {/* Farmer Name */}
            <div className="space-y-1.5">
              <label className="text-[10px] font-bold text-slate-700 dark:text-slate-400 uppercase tracking-wider block">{t('declare.farmerName')}</label>
              <input
                type="text"
                name="farmerName"
                placeholder="e.g. Ramesh Gowda"
                value={form.farmerName}
                onChange={handleChange}
                required
                className="w-full bg-white border border-slate-200 rounded-xl p-3 text-xs placeholder-slate-400 focus:outline-none focus:border-emerald-500 transition-all font-medium dark:bg-slate-900/60 dark:border-white/10 dark:text-white"
              />
            </div>

            {/* Phone */}
            <div className="space-y-1.5">
              <label className="text-[10px] font-bold text-slate-700 dark:text-slate-400 uppercase tracking-wider block">{t('declare.phone')}</label>
              <input
                type="text"
                name="phone"
                placeholder="10-digit mobile number"
                value={form.phone}
                onChange={handleChange}
                required
                className="w-full bg-white border border-slate-200 rounded-xl p-3 text-xs placeholder-slate-400 focus:outline-none focus:border-emerald-500 transition-all font-mono dark:bg-slate-900/60 dark:border-white/10 dark:text-white"
              />
            </div>

            {/* Village */}
            <div className="space-y-1.5">
              <label className="text-[10px] font-bold text-slate-700 dark:text-slate-400 uppercase tracking-wider block">Village</label>
              <input
                type="text"
                name="village"
                placeholder="e.g. Kurubur"
                value={form.village}
                onChange={handleChange}
                required
                className="w-full bg-white border border-slate-200 rounded-xl p-3 text-xs placeholder-slate-400 focus:outline-none focus:border-emerald-500 transition-all font-medium dark:bg-slate-900/60 dark:border-white/10 dark:text-white"
              />
            </div>

            {/* District & Crop selects row */}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <label className="text-[10px] font-bold text-slate-700 dark:text-slate-400 uppercase tracking-wider block">{t('declare.district')}</label>
                <select
                  name="district"
                  value={form.district}
                  onChange={handleChange}
                  className="w-full bg-white border border-slate-200 p-2.5 text-xs font-bold text-slate-800 focus:outline-none focus:border-slate-350 rounded-xl cursor-pointer dark:bg-slate-900/60 dark:border-white/10 dark:text-slate-200"
                >
                  {districts.map((dist, idx) => (
                    <option key={idx} value={dist}>{dist}</option>
                  ))}
                </select>
              </div>

              <div className="space-y-1.5">
                <label className="text-[10px] font-bold text-slate-700 dark:text-slate-400 uppercase tracking-wider block">{t('declare.crop')}</label>
                <select
                  name="crop"
                  value={form.crop}
                  onChange={handleChange}
                  className="w-full bg-white border border-slate-200 p-2.5 text-xs font-bold text-slate-800 focus:outline-none focus:border-slate-350 rounded-xl cursor-pointer dark:bg-slate-900/60 dark:border-white/10 dark:text-slate-200"
                >
                  {crops.map((cr, idx) => (
                    <option key={idx} value={cr}>{cr}</option>
                  ))}
                </select>
              </div>
            </div>

            {/* Acreage & Season row */}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <label className="text-[10px] font-bold text-slate-700 dark:text-slate-400 uppercase tracking-wider block">{t('declare.area')}</label>
                <input
                  type="number"
                  step="0.1"
                  name="areaAcres"
                  placeholder="e.g. 2.5"
                  value={form.areaAcres}
                  onChange={handleChange}
                  required
                  className="w-full bg-white border border-slate-200 rounded-xl p-3 text-xs placeholder-slate-400 focus:outline-none focus:border-emerald-500 transition-all font-medium dark:bg-slate-900/60 dark:border-white/10 dark:text-white"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-[10px] font-bold text-slate-700 dark:text-slate-400 uppercase tracking-wider block">Season</label>
                <select
                  name="season"
                  value={form.season}
                  onChange={handleChange}
                  className="w-full bg-white border border-slate-200 p-2.5 text-xs font-bold text-slate-800 focus:outline-none focus:border-slate-350 rounded-xl cursor-pointer dark:bg-slate-900/60 dark:border-white/10 dark:text-slate-200"
                >
                  {get_season_options().map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-emerald-500 hover:bg-emerald-600 disabled:bg-slate-300 text-slate-950 text-xs font-black py-3 rounded-xl uppercase tracking-wider shadow-lg shadow-emerald-500/10 flex items-center justify-center gap-2 transition-all mt-4"
            >
              {loading ? (
                <span>Registering plan...</span>
              ) : (
                <>
                  <Send className="h-3.5 w-3.5" />
                  <span>{t('declare.submitBtn')}</span>
                </>
              )}
            </button>
          </form>
        </div>

        {/* Right: Success Receipt display panel (6 col) */}
        <div className="lg:col-span-6 bg-white border border-slate-200 rounded-2xl p-5 flex flex-col justify-between h-[520px] lg:h-auto shadow-sm dark:bg-white/5 dark:backdrop-blur-xl dark:border-white/10">
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-900 dark:text-white flex items-center gap-1.5 border-b border-slate-100 dark:border-white/5 pb-3 mb-4 shrink-0">
            <Sparkles className="h-4 w-4 text-emerald-500" /> Sowing Saturation Feedback Receipt
          </h3>

          <div className="flex-1 overflow-y-auto pr-2">
            {loading ? (
              <div className="h-full flex flex-col items-center justify-center space-y-3 text-slate-600">
                <div className="h-7 w-7 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin"></div>
                <span className="text-xs font-bold animate-pulse uppercase tracking-wider font-mono">Writing entry and calculating saturation...</span>
              </div>
            ) : receipt ? (
              <div className="space-y-5 animate-fade-in">
                
                {/* Visual Saturation badge */}
                <div className="border border-slate-200 dark:border-white/10 rounded-2xl p-5 bg-slate-50 dark:bg-white/[0.02] flex items-center justify-between">
                  <div className="space-y-1">
                    <span className="text-[10px] font-bold text-slate-600 dark:text-slate-500 uppercase tracking-widest block">REGIONAL SATURATION</span>
                    <span className="text-lg font-black text-slate-950 dark:text-white">{receipt.saturation.crop} in {receipt.saturation.district}</span>
                  </div>
                  <div className="text-right">
                    <span className="text-3xl font-black text-slate-950 dark:text-white block">{receipt.saturation.saturation_pct.toFixed(0)}%</span>
                    <span className="text-[9px] font-bold uppercase tracking-wider text-red-500">{receipt.saturation.risk_level} RISK</span>
                  </div>
                </div>

                {/* SMS display card */}
                <div className="space-y-2">
                  <span className="text-[10px] font-bold text-slate-700 uppercase tracking-wider block">Generated Kannada WhatsApp / SMS Receipt</span>
                  <div className="bg-emerald-50/20 border border-emerald-200/60 dark:bg-emerald-500/10 dark:border-emerald-500/20 text-slate-950 dark:text-slate-200 p-5 rounded-2xl font-mono text-xs shadow-inner leading-relaxed whitespace-pre-wrap">
                    {receipt.reply}
                  </div>
                </div>

              </div>
            ) : (
              <div className="h-full flex flex-col items-center justify-center text-center space-y-2 p-6">
                <ClipboardCheck className="h-8 w-8 text-slate-400 dark:text-slate-500" />
                <h4 className="text-xs font-bold text-slate-700 dark:text-slate-400 uppercase tracking-wider">No active declaration submission</h4>
                <p className="text-[11px] text-slate-600 dark:text-slate-500 max-w-xs">
                  Fill in your farming declaration on the left to submit it. Your plan will instantly reflect inside the market saturation dashboards.
                </p>
              </div>
            )}
          </div>

          <div className="bg-slate-50 border-t border-slate-200 dark:bg-white/[0.02] dark:border-white/5 p-3.5 text-[10px] font-mono font-bold text-slate-600 dark:text-slate-500 flex items-center gap-2 rounded-b-xl shrink-0 mt-4">
            <ArrowRight className="h-3.5 w-3.5 text-emerald-500" />
            <span>SUBMISSIONS SYNC DIRECTLY TO POSTGRESQL CROPDECLARATION SCHEMA.</span>
          </div>
        </div>

      </div>
    </div>
  );
}
