// src/components/Layout.jsx
import React, { useState, useEffect } from 'react';
import { NavLink, Outlet, useNavigate, useLocation } from 'react-router-dom';
import { Search, Terminal, BarChart2, Users, Settings, MessageSquare, LogOut, CloudRain, Sparkles, ClipboardList, Menu, X, Sun, Moon, Languages, HelpCircle, Calendar, Download, Clock } from 'lucide-react';
import { Toaster } from 'react-hot-toast';
import { useTranslation } from 'react-i18next';
import { API } from '../config';
import { fetchJson, cachedGet, apiUrl } from '../api';
import CropCalendarModal from './CropCalendarModal';

export default function Layout() {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchQuery, setSearchQuery] = useState('');
  const [tickerString, setTickerString] = useState('LOADING LIVE MARKET DATA...');
  const [lastRefreshed, setLastRefreshed] = useState(null);
  const [kolarSaturation, setKolarSaturation] = useState('—');
  const [totalDeclarations, setTotalDeclarations] = useState(0);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [isCalendarOpen, setIsCalendarOpen] = useState(false);
  const [deferredPrompt, setDeferredPrompt] = useState(null);
  const [showInstallBanner, setShowInstallBanner] = useState(false);
  const [darkMode, setDarkMode] = useState(() => {
    return localStorage.getItem('theme') === 'dark' || (!('theme' in localStorage) && window.matchMedia('(prefers-color-scheme: dark)').matches);
  });
  const { i18n } = useTranslation();
  const toggleLanguage = () => {
    i18n.changeLanguage(i18n.language === 'en' ? 'kn' : 'en');
  };

  const isAdmin = localStorage.getItem('role') === 'admin' && localStorage.getItem('auth_token') !== null;

  // PWA Install Prompt Listener
  useEffect(() => {
    const handleBeforeInstallPrompt = (e) => {
      e.preventDefault();
      setDeferredPrompt(e);
      setShowInstallBanner(true);
    };
    window.addEventListener('beforeinstallprompt', handleBeforeInstallPrompt);
    return () => window.removeEventListener('beforeinstallprompt', handleBeforeInstallPrompt);
  }, []);

  const handleInstallPWA = () => {
    if (deferredPrompt) {
      deferredPrompt.prompt();
      deferredPrompt.userChoice.then((choiceResult) => {
        if (choiceResult.outcome === 'accepted') {
          setShowInstallBanner(false);
        }
        setDeferredPrompt(null);
      });
    }
  };

  useEffect(() => {
    if (location.pathname === '/') {
      if (isAdmin) {
        navigate('/admin', { replace: true });
      } else {
        navigate('/farmer', { replace: true });
      }
    }
  }, [location, isAdmin, navigate]);

  useEffect(() => {
    if (darkMode) {
      document.documentElement.classList.add('dark');
      localStorage.setItem('theme', 'dark');
    } else {
      document.documentElement.classList.remove('dark');
      localStorage.setItem('theme', 'light');
    }
  }, [darkMode]);

  useEffect(() => {
    const ctrl = new AbortController();
    // 1. Fetch live ticker prices with explicit trend arrows & timestamp
    const fetchWatchlist = () => {
      fetchJson(apiUrl('/prices/latest-watch'), { signal: ctrl.signal })
        .then(data => {
          if (Array.isArray(data) && data.length > 0) {
            const tickerStr = data
              .map(item => {
                // The API no longer sends invented reference prices: a crop with
                // no mandi row arrives as price=null and must render as such.
                if (item.price == null) {
                  return `${String(item.crop).toUpperCase()}: NO VERIFIED DATA`;
                }
                const mandi = (item.mandi || 'unknown').split(' ')[0];
                const price = `₹${Number(item.price).toLocaleString('en-IN')}`;
                // delta is a rupee movement (it always was) and only exists when
                // the previous observation came from the SAME mandi.
                const move = item.delta == null
                  ? '— no same-mandi change'
                  : `${item.delta >= 0 ? '🟢 ▲ +' : '🔴 ▼ '}${item.delta.toFixed(0)}`;
                const age = item.stale
                  ? ` ⚠ ${item.days_old}d old (${item.as_of})`
                  : (item.as_of ? ` · ${item.as_of}` : '');
                return `${String(item.crop).toUpperCase()} (${mandi}): ${price} [${move}]${age}`;
              })
              .join('   •   ');
            setTickerString(tickerStr);
            setLastRefreshed(new Date());
          }
        })
        .catch(err => {
          // A hung/sleeping backend must not leave the ticker claiming
          // "LOADING…" forever — say what actually happened; the 60s
          // interval retries and this clears on the next success.
          console.error("Error loading watchlist", err);
          setTickerString('MARKET DATA TEMPORARILY UNAVAILABLE — RETRYING EVERY 60s');
        });
    };

    fetchWatchlist();
    const intervalId = setInterval(fetchWatchlist, 60000); // refresh every min

    // 2. Fetch Kolar Tomato Saturation & declarations total
    cachedGet(apiUrl('/declarations/summary'), { signal: ctrl.signal })
      .then(data => {
        setTotalDeclarations(data.total_declarations || 0);
      })
      .catch(err => console.error("Error loading declarations summary", err));

    fetchJson(apiUrl('/saturation/Kolar/Tomato'), { signal: ctrl.signal })
      .then(data => {
        // Report the backend's own figure. This used to divide by a hardcoded
        // 175-acre "hub capacity" that no endpoint, model or bot recognises, so
        // the header disagreed with every other saturation number on screen.
        setKolarSaturation(
          Number.isFinite(data.saturation_pct) ? `${Math.round(data.saturation_pct)}%` : 'NO DATA'
        );
      })
      .catch(err => {
        console.error("Error loading Kolar saturation", err);
        setKolarSaturation('—');
      });

    return () => { clearInterval(intervalId); ctrl.abort(); };
  }, []);

  // Format freshness string e.g. "Updated: Just now" or "Updated: X mins ago"
  const getFreshnessString = () => {
    if (!lastRefreshed) return 'Updating...';
    const diffSecs = Math.floor((new Date() - lastRefreshed) / 1000);
    if (diffSecs < 30) return 'Updated: Just now';
    if (diffSecs < 60) return `Updated: ${diffSecs}s ago`;
    const mins = Math.floor(diffSecs / 60);
    return `Updated: ${mins} min${mins > 1 ? 's' : ''} ago`;
  };

  // Close drawer on path change
  useEffect(() => {
    setIsMobileMenuOpen(false);
  }, [location]);

  const handleLogout = async () => {
    const token = localStorage.getItem('auth_token');
    if (token) {
      try {
        await fetch(`${API}/auth/logout`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${token}`
          }
        });
      } catch (err) {
        console.error("Logout failed:", err);
      }
    }
    localStorage.removeItem('auth_token');
    localStorage.removeItem('auth_status');
    localStorage.removeItem('role');
    navigate('/terminal');
  };

  const handleAdminLogin = () => {
    navigate('/login');
  };

  // Nav item list node rendering helper to avoid duplicates
  const renderNavLinks = () => (
    <>
      {isAdmin ? (
        <>
          <div className="px-3 py-2 text-[9px] font-bold text-slate-400 uppercase tracking-widest">
            ADMIN CONSOLE
          </div>

          <NavLink
            to="/admin"
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 text-xs font-bold uppercase tracking-wider rounded-xl transition-all ${
                isActive
                  ? 'bg-gradient-to-r from-emerald-500 to-teal-600 text-white shadow-md shadow-emerald-500/10'
                  : 'text-slate-200 hover:bg-slate-800/40 hover:text-white'
              }`
            }
          >
            <Users className="h-4 w-4 shrink-0" />
            <span>Farmers Registry</span>
          </NavLink>

          <NavLink
            to="/bot-monitor"
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 text-xs font-bold uppercase tracking-wider rounded-xl transition-all ${
                isActive
                  ? 'bg-gradient-to-r from-emerald-500 to-teal-600 text-white shadow-md shadow-emerald-500/10'
                  : 'text-slate-200 hover:bg-slate-800/40 hover:text-white'
              }`
            }
          >
            <MessageSquare className="h-4 w-4 shrink-0" />
            <span>Bot Transcripts</span>
          </NavLink>

          <NavLink
            to="/terminal"
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 text-xs font-bold uppercase tracking-wider rounded-xl transition-all ${
                isActive
                  ? 'bg-gradient-to-r from-emerald-500 to-teal-600 text-white shadow-md shadow-emerald-500/10'
                  : 'text-slate-200 hover:bg-slate-800/40 hover:text-white'
              }`
            }
          >
            <Terminal className="h-4 w-4 shrink-0" />
            <span>Market Sandbox</span>
          </NavLink>

          <NavLink
            to="/insights"
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 text-xs font-bold uppercase tracking-wider rounded-xl transition-all ${
                isActive
                  ? 'bg-gradient-to-r from-emerald-500 to-teal-600 text-white shadow-md shadow-emerald-500/10'
                  : 'text-slate-200 hover:bg-slate-800/40 hover:text-white'
              }`
            }
          >
            <BarChart2 className="h-4 w-4 shrink-0" />
            <span>Intervention Radar</span>
          </NavLink>

          <NavLink
            to="/settings"
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 text-xs font-bold uppercase tracking-wider rounded-xl transition-all ${
                isActive
                  ? 'bg-gradient-to-r from-emerald-500 to-teal-600 text-white shadow-md shadow-emerald-500/10'
                  : 'text-slate-200 hover:bg-slate-800/40 hover:text-white'
              }`
            }
          >
            <Settings className="h-4 w-4 shrink-0" />
            <span>System settings</span>
          </NavLink>
        </>
      ) : (
        <>
          <div className="px-3 py-2 text-[9px] font-bold text-slate-400 uppercase tracking-widest">
            FARMER WORKSPACE
          </div>

          <NavLink
            to="/farmer"
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 text-xs font-bold uppercase tracking-wider rounded-xl transition-all ${
                isActive
                  ? 'bg-gradient-to-r from-emerald-500 to-teal-600 text-white shadow-md shadow-emerald-500/10'
                  : 'text-slate-200 hover:bg-slate-800/40 hover:text-white'
              }`
            }
          >
            <Sparkles className="h-4 w-4 shrink-0 text-emerald-500" />
            <span>AI Agronomist</span>
          </NavLink>

          <NavLink
            to="/weather"
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 text-xs font-bold uppercase tracking-wider rounded-xl transition-all ${
                isActive
                  ? 'bg-gradient-to-r from-emerald-500 to-teal-600 text-white shadow-md shadow-emerald-500/10'
                  : 'text-slate-200 hover:bg-slate-800/40 hover:text-white'
              }`
            }
          >
            <CloudRain className="h-4 w-4 shrink-0" />
            <span>Climate Forecast</span>
          </NavLink>

          <NavLink
            to="/declare"
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 text-xs font-bold uppercase tracking-wider rounded-xl transition-all ${
                isActive
                  ? 'bg-gradient-to-r from-emerald-500 to-teal-600 text-white shadow-md shadow-emerald-500/10'
                  : 'text-slate-200 hover:bg-slate-800/40 hover:text-white'
              }`
            }
          >
            <ClipboardList className="h-4 w-4 shrink-0" />
            <span>Register Sowing Plan</span>
          </NavLink>

          <NavLink
            to="/terminal"
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 text-xs font-bold uppercase tracking-wider rounded-xl transition-all ${
                isActive
                  ? 'bg-gradient-to-r from-emerald-500 to-teal-600 text-white shadow-md shadow-emerald-500/10'
                  : 'text-slate-200 hover:bg-slate-800/40 hover:text-white'
              }`
            }
          >
            <Terminal className="h-4 w-4 shrink-0" />
            <span>Market Prices</span>
          </NavLink>

          <NavLink
            to="/insights"
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 text-xs font-bold uppercase tracking-wider rounded-xl transition-all ${
                isActive
                  ? 'bg-gradient-to-r from-emerald-500 to-teal-600 text-white shadow-md shadow-emerald-500/10'
                  : 'text-slate-200 hover:bg-slate-800/40 hover:text-white'
              }`
            }
          >
            <BarChart2 className="h-4 w-4 shrink-0" />
            <span>Saturation Index</span>
          </NavLink>

          <button
            onClick={() => setIsCalendarOpen(true)}
            className="w-full flex items-center gap-3 px-3 py-2.5 text-xs font-bold uppercase tracking-wider rounded-xl transition-all text-emerald-400 hover:bg-emerald-500/10 border border-emerald-500/20"
          >
            <Calendar className="h-4 w-4 shrink-0 text-emerald-400" />
            <span>Crop Calendar</span>
          </button>
        </>
      )}
    </>
  );

  const renderSidebarFooter = () => (
    <div className="p-3 border-t border-slate-800 bg-slate-950/40 flex flex-col gap-2.5 text-[10px] font-mono font-bold text-slate-500">
      <div 
        className="flex items-center justify-between text-red-400 bg-red-500/10 border border-red-500/20 px-2.5 py-1.5 rounded-lg cursor-help"
        title="District-wide crop sowing saturation risk level (e.g. Kolar Tomato). High percentages indicate oversupply risk."
      >
        <span className="flex items-center gap-1">
          <HelpCircle className="h-3.5 w-3.5 shrink-0" />
          RISK LEVEL:
        </span>
        <span>🚨 KOLAR {kolarSaturation}</span>
      </div>
      
      {isAdmin ? (
        <button
          onClick={handleLogout}
          className="w-full flex items-center justify-center gap-2 bg-slate-800 hover:bg-red-950 hover:text-red-400 border border-slate-750 hover:border-red-900 py-2 rounded-xl text-[10px] text-slate-350 transition-all font-sans font-bold uppercase tracking-wider shadow-inner"
        >
          <LogOut className="h-3.5 w-3.5" />
          <span>Terminate Session</span>
        </button>
      ) : (
        <button
          onClick={handleAdminLogin}
          className="w-full flex items-center justify-center gap-2 bg-slate-800 hover:bg-slate-750 text-slate-300 border border-slate-700/60 py-2.5 rounded-xl text-[10px] font-sans font-bold uppercase tracking-wider shadow-md transition-all animate-pulse"
        >
          <Settings className="h-3.5 w-3.5" />
          <span>Admin Console</span>
        </button>
      )}
      
      <div className="flex justify-between px-1 text-[8.5px] text-slate-400 border-t border-slate-800 pt-2">
        <span>ROLE: {isAdmin ? 'ADMIN' : 'FARMER/PUBLIC'}</span>
        <span>DATA: {totalDeclarations} RECS</span>
      </div>
    </div>
  );

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-slate-50 dark:bg-slate-950 font-sans text-slate-800 dark:text-slate-200 relative transition-colors">
      
      {/* 1. Desktop Left Sidebar - Pitch Dark theme */}
      <aside className="hidden lg:flex w-64 bg-slate-900 dark:bg-slate-900 text-slate-300 border-r border-slate-800/40 dark:border-white/10 flex-col justify-between z-10 shrink-0 transition-colors">
        <div className="flex flex-col flex-1">
          {/* Logo Section */}
          <div className="p-4 flex items-center gap-3 border-b border-slate-800/60">
            <div className="h-6 w-6 bg-gradient-to-r from-emerald-500 to-teal-500 text-slate-950 flex items-center justify-center font-black text-xs rounded-lg shadow-md shadow-emerald-500/10">
              {isAdmin ? '🛡️' : '🌾'}
            </div>
            <span className="text-xs font-black tracking-widest text-white uppercase font-sans">
              {isAdmin ? 'KM Command' : 'KM Farmer'}
            </span>
          </div>

          {/* Search Box */}
          <div className="p-3 border-b border-slate-800/60">
            <div className="relative flex items-center bg-slate-800/30 border border-slate-800/60 rounded-xl">
              <Search className="absolute left-3 h-3.5 w-3.5 text-slate-400" />
              <input
                type="text"
                placeholder="Search resources..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-9 pr-3 py-2 text-xs text-white bg-transparent placeholder-slate-400 outline-none"
              />
            </div>
          </div>

          {/* Navigation links */}
          <nav className="p-3 space-y-1">
            {renderNavLinks()}
          </nav>
        </div>

        {/* Status footer */}
        {renderSidebarFooter()}
      </aside>

      {/* 2. Responsive Mobile Drawer Overlay & Panel */}
      {isMobileMenuOpen && (
        <div className="lg:hidden fixed inset-0 z-50 flex">
          {/* Background backdrop blur */}
          <div 
            onClick={() => setIsMobileMenuOpen(false)}
            className="fixed inset-0 bg-slate-950/60 backdrop-blur-sm transition-opacity"
          ></div>
          
          {/* Drawer Panel */}
          <div className="relative flex flex-col w-64 max-w-xs bg-slate-900 dark:bg-slate-900 text-slate-300 border-r border-slate-800/40 dark:border-white/10 shadow-2xl transition-transform duration-300">
            {/* Header close panel */}
            <div className="p-4 flex justify-between items-center border-b border-slate-800/60">
              <span className="text-xs font-black tracking-widest text-white uppercase">
                {isAdmin ? 'KM Command' : 'KM Farmer'}
              </span>
              <button 
                onClick={() => setIsMobileMenuOpen(false)}
                className="p-1 text-slate-400 hover:text-white hover:bg-[#1C2541]/60 rounded-lg transition-colors"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* Menu List */}
            <nav className="p-3 space-y-1 flex-1 overflow-y-auto">
              {renderNavLinks()}
            </nav>

            {/* Status Footer */}
            {renderSidebarFooter()}
          </div>
        </div>
      )}

      {/* 3. Right Canvas Area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Header bar (Responsive padding & Mobile hamburger indicator) */}
        <header className="h-14 bg-white dark:bg-slate-950 border-b border-slate-200/80 dark:border-white/10 flex items-center justify-between px-4 lg:px-6 shrink-0 shadow-sm z-20 transition-colors">
          <div className="flex items-center gap-3">
            {/* Hamburger Button for Mobile */}
            <button
              onClick={() => setIsMobileMenuOpen(true)}
              className="lg:hidden p-1.5 hover:bg-slate-100 border border-slate-200 text-slate-600 rounded-lg transition-all"
            >
              <Menu className="h-4.5 w-4.5" />
            </button>

            <span className="text-[10px] font-mono font-bold text-emerald-600 bg-emerald-50 border border-emerald-250 px-2 py-0.5 rounded-md hidden sm:inline-block">
              V2.0
            </span>
            <span className="text-xs font-black tracking-wider text-slate-400 uppercase truncate max-w-[150px] sm:max-w-none">
              {isAdmin ? '🛡️ KISANMITRA - Admin' : '🌾 KISANMITRA'}
            </span>
          </div>

          {/* Scrolling Ticker & Freshness timestamp (Hidden on small mobile) */}
          <div className="flex-1 max-w-md xl:max-w-xl mx-4 overflow-hidden relative h-7 px-3 hidden md:flex items-center gap-3 bg-slate-50 dark:bg-slate-900/60 rounded-xl border border-slate-200/60 dark:border-white/5">
            <div className="flex items-center gap-1 shrink-0 px-1.5 py-0.5 text-[9px] font-mono font-bold text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-500/10 rounded-md border border-emerald-500/20">
              <Clock className="w-3 h-3 animate-pulse" />
              <span>{getFreshnessString()}</span>
            </div>
            <div className="flex-1 overflow-hidden relative">
              <div className="animate-marquee whitespace-nowrap text-xs font-mono font-bold text-slate-600 dark:text-slate-300">
                {tickerString}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2.5 sm:gap-3 shrink-0">
            {/* Crop Calendar Button */}
            <button
              onClick={() => setIsCalendarOpen(true)}
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-emerald-500/30 text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-500/10 text-[10px] font-bold uppercase tracking-wider hover:bg-emerald-500/20 transition-all cursor-pointer shadow-sm"
              title="View Crop Sowing Calendar"
            >
              <Calendar className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Crop Calendar</span>
            </button>

            {/* Language Toggle */}
            <button
              onClick={toggleLanguage}
              className="flex items-center gap-1.5 p-1.5 px-2 rounded-lg border border-slate-200 text-[10px] font-bold text-slate-600 hover:bg-slate-50 transition-colors"
              title="Toggle Language"
            >
              <Languages className="h-3.5 w-3.5" />
              <span>{i18n.language === 'en' ? 'EN' : 'KN'}</span>
            </button>

            {/* Theme Toggle */}
            <button
              onClick={() => setDarkMode(!darkMode)}
              className="p-1.5 rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50 transition-colors"
              title="Toggle Theme"
            >
              {darkMode ? <Sun className="h-4 w-4 text-orange-400" /> : <Moon className="h-4 w-4 text-slate-700" />}
            </button>

            {/* DB Connection Indicator */}
            <div className="flex items-center gap-1.5 text-[9px] sm:text-[10px] font-bold uppercase tracking-wider bg-emerald-50 border border-emerald-250 text-emerald-600 px-2 py-0.5 sm:px-2.5 sm:py-1 rounded-lg">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
              <span className="hidden sm:inline">Live Connect</span>
              <span className="sm:hidden">Live</span>
            </div>
          </div>
        </header>

        {/* PWA Install Banner */}
        {showInstallBanner && (
          <div className="bg-gradient-to-r from-emerald-600 to-teal-700 text-white px-4 py-2 flex items-center justify-between shadow-md z-30 animate-fade-in text-xs font-sans">
            <div className="flex items-center gap-2 font-medium">
              <Download className="w-4 h-4 text-emerald-200 animate-bounce" />
              <span>Install KisanMitra App on your Home Screen for instant offline access.</span>
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={handleInstallPWA}
                className="px-3 py-1 bg-white text-emerald-800 hover:bg-emerald-50 font-bold rounded-lg uppercase tracking-wider text-[10px] shadow-sm transition-all"
              >
                Add to Home Screen
              </button>
              <button
                onClick={() => setShowInstallBanner(false)}
                className="text-white/80 hover:text-white p-1"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}

        {/* Viewport Canvas wrapper */}
        <main className="flex-1 overflow-auto p-4 sm:p-6 bg-slate-50 dark:bg-slate-950 transition-colors">
          <div className="max-w-6xl mx-auto space-y-6">
            <Outlet />
          </div>
        </main>
      </div>

      <CropCalendarModal isOpen={isCalendarOpen} onClose={() => setIsCalendarOpen(false)} />

      <Toaster 
        position="bottom-right"
        toastOptions={{
          style: {
            fontSize: '12px',
            fontFamily: 'monospace',
            fontWeight: 'bold',
            borderRadius: '12px',
            background: darkMode ? '#1e293b' : '#fff',
            color: darkMode ? '#f8fafc' : '#0f172a',
            border: darkMode ? '1px solid rgba(255,255,255,0.1)' : '1px solid rgba(0,0,0,0.1)',
          }
        }} 
      />

      <style>{`
        @keyframes marquee {
          0% { transform: translateX(100%); }
          100% { transform: translateX(-100%); }
        }
        .animate-marquee {
          animation: marquee 30s linear infinite;
        }
      `}</style>
    </div>
  );
}
