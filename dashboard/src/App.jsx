import { useState, useEffect } from "react";
import axios from "axios";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine
} from "recharts";

const API = import.meta.env.VITE_API_URL || "";

const CROPS = ["Tomato", "Potato", "Onion", "Marigold"];
const DISTRICTS = ["Chikkaballapur", "Kolar"];

function RiskBadge({ level }) {
  const styles = {
    LOW:    { bg: "rgba(16, 185, 129, 0.15)", color: "#34d399", emoji: "🟢" },
    MEDIUM: { bg: "rgba(245, 158, 11, 0.15)", color: "#fbbf24", emoji: "🟡" },
    HIGH:   { bg: "rgba(239, 68, 68, 0.15)", color: "#f87171", emoji: "🔴" },
  };
  const s = styles[level] || styles.LOW;
  return (
    <span style={{
      background: s.bg, color: s.color, padding: "6px 14px",
      borderRadius: 20, fontWeight: 700, fontSize: 12, letterSpacing: "0.05em",
      border: `1px solid ${s.color}40`
    }}>
      {s.emoji} {level} RISK
    </span>
  );
}

function StatCard({ title, value, sub, icon }) {
  return (
    <div className="glass-panel" style={{ padding: "24px", display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "16px" }}>
        <p style={{ color: "var(--text-secondary)", fontSize: 14, margin: 0, fontWeight: 500 }}>{title}</p>
        <div style={{ fontSize: 20, opacity: 0.8 }}>{icon}</div>
      </div>
      <div>
        <p style={{ fontSize: 32, fontWeight: 800, margin: "0 0 4px 0", color: "var(--text-primary)" }}>{value}</p>
        {sub && <p style={{ color: "var(--text-secondary)", fontSize: 12, margin: 0 }}>{sub}</p>}
      </div>
    </div>
  );
}

const CustomTooltip = ({ active, payload, label }) => {
  if (active && payload && payload.length) {
    return (
      <div style={{
        background: "rgba(15, 23, 42, 0.85)", backdropFilter: "blur(8px)",
        border: "1px solid rgba(255,255,255,0.1)", padding: "12px", borderRadius: "8px",
        color: "#fff"
      }}>
        <p style={{ margin: "0 0 8px 0", fontSize: 12, color: "var(--text-secondary)" }}>{label}</p>
        <p style={{ margin: 0, fontWeight: 700, color: "var(--accent-secondary)" }}>
          ₹{payload[0].value} / quintal
        </p>
      </div>
    );
  }
  return null;
};

export default function App() {
  const [health, setHealth]       = useState(null);
  const [summary, setSummary]     = useState(null);
  const [saturation, setSaturation] = useState({});
  const [prediction, setPrediction] = useState(null);
  const [priceInput, setPriceInput] = useState(2100);
  const [selectedCrop, setSelectedCrop]   = useState("Tomato");
  const [selectedDistrict, setSelectedDistrict] = useState("Chikkaballapur");
  const [loading, setLoading]     = useState(false);
  const [error, setError]         = useState(null);

  const [priceHistory, setPriceHistory] = useState([]);
  const [chartData, setChartData] = useState([]);

  useEffect(() => {
    fetchAll();
  }, []);

  useEffect(() => {
    fetchSaturation();
    fetchPriceHistory();
  }, [selectedCrop, selectedDistrict]);

  async function fetchAll() {
    try {
      const [h, s] = await Promise.all([
        axios.get(`${API}/health`),
        axios.get(`${API}/declarations/summary`),
      ]);
      setHealth(h.data);
      setSummary(s.data);
    } catch (e) {
      setError("Cannot reach API — make sure FastAPI is running on port 8000");
    }
  }

  async function fetchSaturation() {
    try {
      const res = await axios.get(
        `${API}/saturation/${selectedDistrict}/${selectedCrop}`
      );
      setSaturation(res.data);
    } catch (e) {}
  }

  async function fetchPriceHistory() {
    try {
      const res = await axios.get(
        `${API}/prices/history/${selectedDistrict}/${selectedCrop}?days=60`
      );
      const history = res.data.map(r => ({
        day: r.date,
        price: r.price,
      }));
      setPriceHistory(history);
      setChartData(history);
    } catch (e) {
      setPriceHistory([]);
      setChartData([]);
    }
  }

  async function fetchPrediction() {
    setLoading(true);
    try {
      const res = await axios.post(`${API}/prices/predict`, {
        commodity: selectedCrop,
        market: selectedDistrict,
        current_price: parseFloat(priceInput),
        arrivals_tonnes: 120,
      });
      const d = res.data;
      setPrediction(d);

      const today = { day: "Today", price: parseFloat(priceInput), current: true };
      const future = { day: "D+60", price: d.predicted_price, predicted: true,
        low: d.confidence_low, high: d.confidence_high };
      setChartData([...priceHistory, today, future]);
    } catch (e) {
      setError("Prediction failed — check API is running");
    }
    setLoading(false);
  }

  const signalStyles = {
    "WAIT — Price likely rising":   { color: "#34d399", bg: "rgba(52, 211, 153, 0.1)" },
    "SELL NOW — Price likely falling": { color: "#f87171", bg: "rgba(248, 113, 113, 0.1)" },
    "NEUTRAL — Monitor weekly":     { color: "#fbbf24", bg: "rgba(251, 191, 36, 0.1)" },
  };

  return (
    <div style={{ paddingBottom: "60px" }}>
      {/* Header */}
      <header style={{
        padding: "20px 40px",
        display: "flex", alignItems: "center", justifyContent: "space-between",
        borderBottom: "1px solid var(--glass-border)",
        background: "rgba(15, 23, 42, 0.8)", backdropFilter: "blur(12px)",
        position: "sticky", top: 0, zIndex: 50
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div style={{ fontSize: 32, background: "rgba(255,255,255,0.1)", borderRadius: "12px", padding: "8px" }}>🌾</div>
          <div>
            <h1 style={{ margin: 0, fontSize: 24, fontWeight: 800, letterSpacing: "-0.02em" }} className="gradient-text">KisanMitra Admin</h1>
            <p style={{ margin: "2px 0 0 0", fontSize: 13, color: "var(--text-secondary)" }}>
              Karnataka Smart Crop Planning Intelligence
            </p>
          </div>
        </div>
        <div className="glass-panel" style={{ padding: "8px 16px", borderRadius: "30px", display: "flex", alignItems: "center", gap: 10 }}>
          <div className="status-dot" style={{ background: health ? "#10b981" : "#ef4444" }} />
          <span style={{ fontSize: 13, fontWeight: 500, color: "var(--text-primary)" }}>
            {health ? "System Operational" : "API Offline"}
          </span>
        </div>
      </header>

      {error && (
        <div style={{ background: "rgba(239, 68, 68, 0.1)", border: "1px solid rgba(239, 68, 68, 0.2)", color: "#fca5a5", padding: "16px", margin: "24px 40px", borderRadius: "12px", fontSize: 14, fontWeight: 500 }}>
          ⚠️ {error}
        </div>
      )}

      <main style={{ padding: "32px 40px", maxWidth: "1400px", margin: "0 auto" }}>
        
        {/* Stat Cards */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 24, marginBottom: 32 }}>
          <StatCard title="Model Accuracy (MAPE)" value="11.98%" sub="Beats 21% ARIMA baseline" icon="🎯" />
          <StatCard title="Total Declarations" value={summary?.total_declarations ?? "—"} sub={`${summary?.total_farmers ?? 0} unique farmers`} icon="📝" />
          <StatCard title="Districts Covered" value={summary?.districts?.length ?? 2} sub="Chikkaballapur · Kolar" icon="🗺️" />
          <StatCard title="Data Freshness" value="Live" sub="n8n auto-fetch + Webhooks" icon="⚡" />
        </div>

        {/* Controls */}
        <div className="glass-panel" style={{ padding: "24px", marginBottom: 32, display: "flex", gap: 24, alignItems: "flex-end", flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: "180px" }}>
            <label style={{ fontSize: 12, fontWeight: 600, color: "var(--text-secondary)", display: "block", marginBottom: 8, letterSpacing: "0.05em" }}>DISTRICT</label>
            <select className="input-modern" value={selectedDistrict} onChange={e => setSelectedDistrict(e.target.value)} style={{ width: "100%", cursor: "pointer" }}>
              {DISTRICTS.map(d => <option key={d} style={{background: "var(--bg-dark)"}}>{d}</option>)}
            </select>
          </div>
          <div style={{ flex: 1, minWidth: "180px" }}>
            <label style={{ fontSize: 12, fontWeight: 600, color: "var(--text-secondary)", display: "block", marginBottom: 8, letterSpacing: "0.05em" }}>CROP</label>
            <select className="input-modern" value={selectedCrop} onChange={e => setSelectedCrop(e.target.value)} style={{ width: "100%", cursor: "pointer" }}>
              {CROPS.map(c => <option key={c} style={{background: "var(--bg-dark)"}}>{c}</option>)}
            </select>
          </div>
          <div style={{ flex: 1, minWidth: "180px" }}>
            <label style={{ fontSize: 12, fontWeight: 600, color: "var(--text-secondary)", display: "block", marginBottom: 8, letterSpacing: "0.05em" }}>CURRENT PRICE (₹/q)</label>
            <input type="number" className="input-modern" value={priceInput} onChange={e => setPriceInput(e.target.value)} style={{ width: "100%" }} />
          </div>
          <button className="btn-primary" onClick={fetchPrediction} disabled={loading} style={{ height: "42px", minWidth: "160px" }}>
            {loading ? "Analyzing..." : "Run ML Inference"}
          </button>
        </div>

        {/* Two columns */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24, marginBottom: 24 }}>
          
          {/* Saturation Card */}
          <div className="glass-panel" style={{ padding: "32px", display: "flex", flexDirection: "column", justifyContent: "center" }}>
            <h3 style={{ margin: "0 0 24px", fontSize: 18, fontWeight: 600, color: "var(--text-primary)", display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{color: "var(--accent-secondary)"}}>⛯</span> District Saturation Index
            </h3>
            {saturation.saturation_pct !== undefined ? (
              <>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
                  <span style={{ fontSize: 64, fontWeight: 800, lineHeight: 1, color: "var(--text-primary)" }}>
                    {saturation.saturation_pct?.toFixed(0)}<span style={{fontSize: 32, opacity: 0.5}}>%</span>
                  </span>
                  <RiskBadge level={saturation.risk_level} />
                </div>
                
                <div style={{ background: "rgba(255,255,255,0.05)", borderRadius: 12, height: 16, marginBottom: 24, overflow: "hidden", border: "1px solid var(--glass-border)" }}>
                  <div style={{
                    height: "100%", borderRadius: 12,
                    width: `${Math.min(saturation.saturation_pct, 100)}%`,
                    background: saturation.risk_level === "HIGH" ? "var(--danger)" : saturation.risk_level === "MEDIUM" ? "var(--warning)" : "var(--success)",
                    transition: "width 1s cubic-bezier(0.4, 0, 0.2, 1)",
                    boxShadow: "0 0 10px rgba(255,255,255,0.2) inset"
                  }} />
                </div>
                
                <div style={{display: "flex", justifyContent: "space-between", padding: "16px", background: "rgba(255,255,255,0.03)", borderRadius: "8px"}}>
                  <div>
                    <p style={{margin: 0, fontSize: 12, color: "var(--text-secondary)"}}>Farmers Declared</p>
                    <p style={{margin: "4px 0 0 0", fontSize: 18, fontWeight: 600}}>{saturation.farmer_count}</p>
                  </div>
                  <div style={{textAlign: "right"}}>
                    <p style={{margin: 0, fontSize: 12, color: "var(--text-secondary)"}}>Total Area</p>
                    <p style={{margin: "4px 0 0 0", fontSize: 18, fontWeight: 600}}>{saturation.total_area} acres</p>
                  </div>
                </div>
              </>
            ) : (
              <div style={{height: "160px", display: "flex", alignItems: "center", justifyContent: "center"}}>
                <div className="status-dot" style={{background: "var(--accent-primary)"}} />
              </div>
            )}
          </div>

          {/* Prediction Card */}
          <div className="glass-panel" style={{ padding: "32px", display: "flex", flexDirection: "column", justifyContent: "center" }}>
            <h3 style={{ margin: "0 0 24px", fontSize: 18, fontWeight: 600, color: "var(--text-primary)", display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{color: "var(--accent-secondary)"}}>🧠</span> 60-Day Price Forecast
            </h3>
            {prediction ? (
              <>
                <div style={{ display: "flex", alignItems: "center", gap: 24, marginBottom: 24, padding: "20px", background: "rgba(255,255,255,0.03)", borderRadius: "12px", border: "1px solid rgba(255,255,255,0.05)" }}>
                  <div style={{ flex: 1 }}>
                    <p style={{ fontSize: 13, color: "var(--text-secondary)", margin: "0 0 4px 0" }}>Current</p>
                    <p style={{ fontSize: 28, fontWeight: 700, color: "var(--text-primary)", margin: 0 }}>
                      ₹{prediction.current_price?.toLocaleString()}
                    </p>
                  </div>
                  <div style={{ width: "32px", height: "32px", borderRadius: "50%", background: "var(--bg-dark)", display: "flex", alignItems: "center", justifyContent: "center", border: "1px solid var(--glass-border)" }}>
                    →
                  </div>
                  <div style={{ flex: 1, textAlign: "right" }}>
                    <p style={{ fontSize: 13, color: "var(--text-secondary)", margin: "0 0 4px 0" }}>Day 60</p>
                    <p style={{ fontSize: 28, fontWeight: 700, color: "var(--accent-secondary)", margin: 0 }}>
                      ₹{prediction.predicted_price?.toLocaleString()}
                    </p>
                  </div>
                </div>
                
                <div style={{
                  background: signalStyles[prediction.signal]?.bg || "rgba(255,255,255,0.05)",
                  borderRadius: 12, padding: "16px 20px", border: `1px solid ${signalStyles[prediction.signal]?.color}40`
                }}>
                  <p style={{
                    margin: "0 0 8px 0", fontWeight: 700, fontSize: 15,
                    color: signalStyles[prediction.signal]?.color || "var(--text-primary)"
                  }}>
                    {prediction.signal}
                  </p>
                  <p style={{ margin: 0, fontSize: 13, color: "var(--text-secondary)" }}>
                    90% Confidence Interval: ₹{prediction.confidence_low} — ₹{prediction.confidence_high}
                  </p>
                </div>
              </>
            ) : (
              <div style={{height: "160px", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-secondary)"}}>
                Run inference to view forecast
              </div>
            )}
          </div>
        </div>

        {/* Price Chart */}
        {chartData.length > 0 && (
          <div className="glass-panel" style={{ padding: "32px" }}>
            <div style={{display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "24px"}}>
              <h3 style={{ margin: 0, fontSize: 18, fontWeight: 600, color: "var(--text-primary)" }}>
                Market Trajectory
              </h3>
              <div style={{display: "flex", gap: "16px"}}>
                <span style={{fontSize: 12, color: "var(--text-secondary)", display: "flex", alignItems: "center", gap: "6px"}}>
                  <span style={{width: "10px", height: "10px", background: "var(--accent-primary)", borderRadius: "2px", display: "inline-block"}}/> Historical
                </span>
                <span style={{fontSize: 12, color: "var(--text-secondary)", display: "flex", alignItems: "center", gap: "6px"}}>
                  <span style={{width: "10px", height: "10px", background: "var(--accent-secondary)", borderRadius: "2px", display: "inline-block", opacity: 0.5}}/> Projected
                </span>
              </div>
            </div>
            <ResponsiveContainer width="100%" height={320}>
              <AreaChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="colorPrice" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="var(--accent-primary)" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="var(--accent-primary)" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
                <XAxis dataKey="day" tick={{ fontSize: 12, fill: "var(--text-secondary)" }} axisLine={false} tickLine={false} interval={4} />
                <YAxis tick={{ fontSize: 12, fill: "var(--text-secondary)" }} axisLine={false} tickLine={false} tickFormatter={v => `₹${v}`} />
                <Tooltip content={<CustomTooltip />} />
                <ReferenceLine x="Today" stroke="var(--text-secondary)" strokeDasharray="4 4" label={{ value: "INFERENCE POINT", position: "insideTopLeft", fill: "var(--text-secondary)", fontSize: 10, dy: -10 }} />
                <Area type="monotone" dataKey="price" stroke="var(--accent-primary)" strokeWidth={3} fillOpacity={1} fill="url(#colorPrice)" activeDot={{ r: 6, fill: "var(--accent-secondary)", stroke: "var(--bg-dark)", strokeWidth: 2 }} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}

      </main>
    </div>
  );
}
