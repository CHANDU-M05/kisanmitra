// src/pages/SettingsView.jsx
import React, { useState, useEffect } from 'react';
import { Settings, Play, Database, RefreshCw, Cpu, Upload } from 'lucide-react';
import { toast, Toaster } from 'react-hot-toast';
import Card from '../components/ui/Card';
import { API } from '../config';

export default function SettingsView() {
  const [syncStatus, setSyncStatus] = useState('IDLE');
  const [loading, setLoading] = useState(false);
  const [systemStatus, setSystemStatus] = useState({
    model_loaded: false,
    declaration_count: 0,
    latest_price_date: null
  });

  const [selectedFile, setSelectedFile] = useState(null);
  const [selectedCrop, setSelectedCrop] = useState('All');
  const [selectedCategory, setSelectedCategory] = useState('General');
  const [selectedLanguage, setSelectedLanguage] = useState('kn');
  const [uploading, setUploading] = useState(false);
  const [logs, setLogs] = useState([]);

  const loadLogs = () => {
    const token = localStorage.getItem('auth_token');
    if (!token) return;
    fetch(`${API}/admin/audit-logs?limit=10`, {
      headers: { 'Authorization': `Bearer ${token}` }
    })
      .then(res => res.ok ? res.json() : [])
      .then(data => setLogs(data))
      .catch(err => console.error("Error loading server audit logs", err));
  };

  const handleUpload = () => {
    if (!selectedFile) {
      toast.error("Please select a file to upload");
      return;
    }
    setUploading(true);
    const token = localStorage.getItem('auth_token');
    const formData = new FormData();
    formData.append('file', selectedFile);
    formData.append('crop', selectedCrop);
    formData.append('category', selectedCategory);
    formData.append('language', selectedLanguage);

    fetch(`${API}/internal/knowledge/upload`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}` },
      body: formData
    })
      .then(res => {
        if (!res.ok) return res.json().then(err => { throw new Error(err.detail || 'Upload failed') });
        return res.json();
      })
      .then(data => {
        toast.success(`Successfully uploaded document! Created ${data.chunks_created} vector chunks.`);
        setSelectedFile(null);
        setUploading(false);
      })
      .catch(err => {
        console.error("Upload error", err);
        toast.error(err.message || "Failed to upload document");
        setUploading(false);
      });
  };

  const fetchStatus = () => {
    const token = localStorage.getItem('auth_token');
    fetch(`${API}/internal/status`, { headers: { 'Authorization': `Bearer ${token}` } })
      .then(res => res.json())
      .then(data => {
        if (data && typeof data === 'object' && !data.detail) {
          setSystemStatus(data);
        } else {
          console.error("Invalid status response:", data);
        }
      })
      .catch(err => console.error("Error fetching system status", err));
  };

  useEffect(() => { fetchStatus(); loadLogs(); }, []);

  const triggerSync = () => {
    setLoading(true);
    setSyncStatus('SYNCING...');
    const token = localStorage.getItem('auth_token');
    
    const promise = fetch(`${API}/internal/sync`, { method: 'POST', headers: { 'Authorization': `Bearer ${token}` } })
      .then(res => {
        if (!res.ok) throw new Error("Pipeline trigger failed");
        return res.json();
      })
      .then((data) => {
        setSyncStatus('SYNC STARTED');
        setTimeout(() => {
          setSyncStatus('IDLE');
          setLoading(false);
          fetchStatus();
        }, 5000);
        return data;
      })
      .catch(err => {
        console.error("Error triggering sync", err);
        setSyncStatus('FAILED');
        setLoading(false);
        throw err;
      });

    toast.promise(promise, {
      loading: 'Triggering fetch & model retraining pipeline in background...',
      success: 'Agmarknet pipeline sync successfully triggered!',
      error: 'Failed to trigger background pipeline sync.'
    });
  };

  const handleRetrainClick = () => {
    const confirmed = window.confirm("Are you sure you want to trigger the data pipeline and retrain the ML model? This will fetch the latest observations from AGMARKNET and retrain the Random Forest model in the background.");
    if (confirmed) triggerSync();
  };

  return (
    <div className="space-y-6">
      <Card className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div className="space-y-1">
          <h2 className="text-sm font-bold uppercase tracking-wider flex items-center gap-2 text-slate-900 dark:text-white">
            <Settings className="h-4 w-4 text-emerald-500" /> System Settings &amp; Operations
          </h2>
          <p className="text-xs text-slate-600">
            Monitor ML models loaded state, backend sync hooks, and database pipeline metrics.
          </p>
        </div>
      </Card>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">

        <Card className="space-y-4">
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-900 dark:text-white flex items-center gap-1.5 border-b border-slate-100 dark:border-white/5 pb-3">
            <Cpu className="h-4 w-4 text-emerald-500" /> Model &amp; Data Summary
          </h3>

          <div className="space-y-3.5 font-mono text-xs text-slate-800 dark:text-slate-300">
            <div className="flex justify-between items-center py-1">
              <span>ML Engine Status:</span>
              <span className={`px-2.5 py-0.5 rounded text-[10px] font-bold ${systemStatus.model_loaded ? 'bg-emerald-50 text-emerald-700 border border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/20' : 'bg-red-50 text-red-700 border border-red-200 dark:bg-red-500/10 dark:text-red-400 dark:border-red-500/20'}`}>
                {systemStatus.model_loaded ? 'ACTIVE REGRESSOR LOADED' : 'NOT LOADED'}
              </span>
            </div>

            <div className="flex justify-between items-center py-1 border-t border-slate-100 dark:border-white/5">
              <span>Total Declarations Ingress:</span>
              <span className="font-bold text-slate-900 dark:text-white">{systemStatus.declaration_count} Records</span>
            </div>

            <div className="flex justify-between items-center py-1 border-t border-slate-100 dark:border-white/5">
              <span>Last Spot Price Date:</span>
              <span className="font-bold text-slate-900 dark:text-white">{systemStatus.latest_price_date ? new Date(systemStatus.latest_price_date).toLocaleDateString() : 'None'}</span>
            </div>
          </div>
        </Card>

        <Card className="flex flex-col justify-between">
          <div>
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-900 dark:text-white flex items-center gap-1.5 border-b border-slate-100 dark:border-white/5 pb-3 mb-3">
              <Database className="h-4 w-4 text-slate-700 dark:text-slate-400" /> Data Pipeline Trigger
            </h3>
            <p className="text-xs text-slate-600 dark:text-slate-500 leading-relaxed mb-4">
              Manually retrieve the latest spot observations from AGMARKNET portals and retrain the pricing prediction Random Forest model.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={handleRetrainClick}
              disabled={loading}
              className="flex-1 flex items-center justify-center gap-2 bg-slate-900 hover:bg-slate-800 dark:bg-emerald-500 dark:text-slate-950 dark:hover:bg-emerald-600 disabled:bg-slate-300 text-white text-xs font-bold py-3 px-4 rounded-xl uppercase tracking-wider shadow-sm transition-all"
            >
              {loading ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4 fill-white" />}
              <span>Retrain &amp; Fetch Pipeline</span>
            </button>

            <span className="font-mono text-[10px] font-bold border border-slate-300 bg-slate-50 text-slate-700 dark:border-white/10 dark:bg-slate-900/60 dark:text-slate-200 px-3 py-2 rounded-xl">
              PIPELINE: {syncStatus}
            </span>
          </div>
        </Card>

        <Card className="flex flex-col justify-between">
          <div>
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-900 dark:text-white flex items-center gap-1.5 border-b border-slate-100 dark:border-white/5 pb-3 mb-3">
              <Database className="h-4 w-4 text-slate-700 dark:text-slate-400" /> Knowledge Ingestion (RAG)
            </h3>
            <p className="text-xs text-slate-600 dark:text-slate-500 leading-relaxed mb-4">
              Add agronomic guide documents or manuals to expand the agronomist bot's retrieval vocabulary. Supports PDF or raw text.
            </p>

            <div className="space-y-3.5 mb-4">
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="text-[10px] font-bold block text-slate-500 uppercase tracking-wider mb-1">Crop Context</label>
                  <select value={selectedCrop} onChange={(e) => setSelectedCrop(e.target.value)}
                    className="w-full bg-slate-50 border border-slate-200 p-2 text-xs font-bold text-slate-800 rounded-xl cursor-pointer dark:bg-slate-900/60 dark:border-white/10 dark:text-slate-200">
                    <option value="All">All Crops</option>
                    <option value="Tomato">Tomato</option>
                    <option value="Potato">Potato</option>
                    <option value="Onion">Onion</option>
                    <option value="Marigold">Marigold</option>
                    <option value="Maize">Maize</option>
                    <option value="Ragi">Ragi</option>
                    <option value="Brinjal">Brinjal</option>
                    <option value="Cabbage">Cabbage</option>
                  </select>
                </div>
                <div>
                  <label className="text-[10px] font-bold block text-slate-500 uppercase tracking-wider mb-1">Category</label>
                  <select value={selectedCategory} onChange={(e) => setSelectedCategory(e.target.value)}
                    className="w-full bg-slate-50 border border-slate-200 p-2 text-xs font-bold text-slate-800 rounded-xl cursor-pointer dark:bg-slate-900/60 dark:border-white/10 dark:text-slate-200">
                    <option value="General">General</option>
                    <option value="Pest Control">Pest Control</option>
                    <option value="Fertilizer">Fertilizer</option>
                    <option value="Weather">Weather</option>
                    <option value="Sowing">Sowing</option>
                  </select>
                </div>
                <div>
                  <label className="text-[10px] font-bold block text-slate-500 uppercase tracking-wider mb-1">Language</label>
                  <select value={selectedLanguage} onChange={(e) => setSelectedLanguage(e.target.value)}
                    className="w-full bg-slate-50 border border-slate-200 p-2 text-xs font-bold text-slate-800 rounded-xl cursor-pointer dark:bg-slate-900/60 dark:border-white/10 dark:text-slate-200">
                    <option value="kn">ಕನ್ನಡ (KN)</option>
                    <option value="en">English (EN)</option>
                  </select>
                </div>
              </div>

              <div className="relative border-2 border-dashed border-slate-200 dark:border-white/10 rounded-xl p-4 flex flex-col items-center justify-center cursor-pointer hover:bg-slate-50/55 dark:hover:bg-white/[0.02] transition-colors">
                <input
                  type="file"
                  accept=".pdf,.txt"
                  onChange={(e) => setSelectedFile(e.target.files[0])}
                  className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                />
                <Upload className="h-5 w-5 text-slate-400 mb-1" />
                <span className="text-xs font-bold text-slate-700 dark:text-slate-400 truncate max-w-full">
                  {selectedFile ? selectedFile.name : "Select PDF/Text file"}
                </span>
                <span className="text-[9px] font-mono text-slate-500 dark:text-slate-500 mt-0.5">Max size: 10MB</span>
              </div>
            </div>
          </div>

          <button
            onClick={handleUpload}
            disabled={uploading || !selectedFile}
            className="w-full flex items-center justify-center gap-2 bg-emerald-500 text-slate-950 hover:bg-emerald-600 disabled:bg-slate-200 disabled:text-slate-400 text-xs font-black py-3 rounded-xl uppercase tracking-wider transition-all shadow-sm"
          >
            {uploading ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4 fill-slate-950" />}
            <span>Ingest &amp; Embed Knowledge</span>
          </button>
        </Card>

        <Card className="flex flex-col justify-between col-span-1 md:col-span-2">
          <div>
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-900 dark:text-white flex items-center gap-1.5 border-b border-slate-100 dark:border-white/5 pb-3 mb-3">
              <Database className="h-4 w-4 text-slate-700 dark:text-slate-400" /> PII Access &amp; CSV Export Audit Logs
            </h3>
            <p className="text-xs text-slate-600 dark:text-slate-500 leading-relaxed mb-4">
              Real-time audit record of access controls under India's Digital Personal Data Protection (DPDP) Act.
            </p>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-[11px] border-collapse font-mono">
                <thead>
                  <tr className="border-b border-slate-200 dark:border-white/5 font-bold uppercase text-[9px] text-slate-500 tracking-wider">
                    <th className="p-2">Timestamp</th>
                    <th className="p-2">Admin User</th>
                    <th className="p-2">Action</th>
                    <th className="p-2 text-right">Target Accessed</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-white/5 text-slate-700 dark:text-slate-400">
                  {logs.length === 0 ? (
                    <tr>
                      <td colSpan="4" className="p-3 text-center text-slate-400 italic">No security access logs registered yet.</td>
                    </tr>
                  ) : (
                    logs.map(log => (
                      <tr key={log.id} className="border-b border-slate-100 dark:border-white/5 last:border-none">
                        <td className="p-2 text-slate-500">{new Date(log.timestamp).toLocaleString()}</td>
                        <td className="p-2 font-bold text-slate-900 dark:text-white">{log.admin}</td>
                        <td className="p-2 font-bold">
                          <span className={`px-1.5 py-0.5 rounded text-[8px] ${log.action === 'EXPORT_CSV' ? 'bg-indigo-50 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-400' : 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-400'}`}>
                            {log.action}
                          </span>
                        </td>
                        <td className="p-2 text-right text-slate-600 dark:text-slate-400 font-semibold">{log.target}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="flex justify-end gap-2 mt-4 pt-3 border-t border-slate-100 dark:border-white/5">
            <button
              onClick={() => {
                localStorage.removeItem('audit_logs');
                loadLogs();
                toast.success("Audit logs cleared successfully.");
              }}
              className="text-[9px] font-bold uppercase tracking-wider px-3 py-1.5 rounded border border-slate-200 hover:border-red-500 bg-slate-50 hover:bg-red-50 text-slate-500 hover:text-red-700 dark:bg-white/5 dark:border-white/10 dark:text-slate-400 dark:hover:bg-red-500/10 dark:hover:text-red-400 transition-all cursor-pointer"
            >
              Clear Logs
            </button>
            <button
              onClick={loadLogs}
              className="text-[9px] font-bold uppercase tracking-wider px-3 py-1.5 rounded bg-emerald-500 hover:bg-emerald-600 text-slate-950 transition-all cursor-pointer"
            >
              Refresh
            </button>
          </div>
        </Card>

      </div>
      <Toaster />
    </div>
  );
}
