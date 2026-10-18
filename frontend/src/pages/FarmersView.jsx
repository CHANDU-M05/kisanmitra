// src/pages/FarmersView.jsx
import React, { useState, useEffect } from 'react';
import { Users, Filter, CheckCircle2, AlertCircle, RefreshCw, Download, ChevronDown, ChevronRight, Trash2 } from 'lucide-react';
import { toast } from 'react-hot-toast';
import Card from '../components/ui/Card';
import { API } from '../config';

// Server-side audit logging for DPDP Act compliance
function logAudit(action, target) {
  const token = localStorage.getItem('auth_token');
  if (!token) return;
  fetch(`${API}/admin/audit-logs`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`
    },
    body: JSON.stringify({ action, target })
  }).catch(err => console.error("Audit log failed:", err));
}

function getStatusBadge(status) {
  switch (status) {
    case 'verified':
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/20">
          <CheckCircle2 className="h-3 w-3" /> VERIFIED
        </span>
      );
    case 'failed':
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-red-50 text-red-700 border border-red-200 dark:bg-red-500/10 dark:text-red-400 dark:border-red-500/20">
          <AlertCircle className="h-3 w-3" /> FAULTY
        </span>
      );
    default:
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-slate-50 text-slate-700 border border-slate-200 dark:bg-white/[0.02] dark:text-slate-400 dark:border-white/5">
          <RefreshCw className="h-2.5 w-2.5 animate-spin" /> PENDING
        </span>
      );
  }
}

export default function FarmersView() {
  const [declarations, setDeclarations] = useState([]);
  const [filteredDeclarations, setFilteredDeclarations] = useState([]);
  const [loading, setLoading] = useState(true);

  const [districts, setDistricts] = useState([]);
  const [crops, setCrops] = useState([]);

  const [selectedDistrict, setSelectedDistrict] = useState('ALL');
  const [selectedCrop, setSelectedCrop] = useState('ALL');
  const [revealedPhones, setRevealedPhones] = useState(new Set());
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedFarmers, setExpandedFarmers] = useState(new Set());

  const handleDeleteDeclaration = (id, cropName) => {
    const confirmed = window.confirm(`Are you sure you want to permanently delete this ${cropName} declaration from the database?`);
    if (!confirmed) return;

    const token = localStorage.getItem('auth_token');
    fetch(`${API}/farmer/declaration/${id}`, {
      method: 'DELETE',
      headers: { 'Authorization': `Bearer ${token}` }
    })
      .then(res => {
        if (!res.ok) throw new Error("Deletion failed");
        return res.json();
      })
      .then(data => {
        if (data.success) {
          toast.success("Declaration deleted from database!");
          setDeclarations(prev => prev.filter(d => d.id !== id));
          logAudit('DELETE_DECLARATION', `Declaration ID: ${id}`);
        }
      })
      .catch(err => {
        console.error("Error deleting declaration", err);
        toast.error("Could not delete declaration from database.");
      });
  };

  const toggleRevealPhone = (key) => {
    setRevealedPhones(prev => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
        logAudit('REVEAL_PII', `Farmer: ${key.split('_')[0]}`);
      }
      return next;
    });
  };

  const toggleExpandFarmer = (key) => {
    setExpandedFarmers(prev => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  };

  const fetchDeclarations = () => {
    setLoading(true);
    const token = localStorage.getItem('auth_token');
    fetch(`${API}/declarations?limit=150`, { headers: { 'Authorization': `Bearer ${token}` } })
      .then(res => res.json())
      .then(data => {
        if (!Array.isArray(data)) {
          console.error("Declarations response is not an array:", data);
          setLoading(false);
          return;
        }
        setDeclarations(data);
        setFilteredDeclarations(data);
        setDistricts(['ALL', ...new Set(data.map(item => item.district))].sort());
        setCrops(['ALL', ...new Set(data.map(item => item.crop))].sort());
        setLoading(false);
      })
      .catch(err => {
        console.error("Error loading declarations", err);
        setLoading(false);
      });
  };

  useEffect(() => { fetchDeclarations(); }, []);

  useEffect(() => {
    let result = declarations;
    if (selectedDistrict !== 'ALL') result = result.filter(item => item.district === selectedDistrict);
    if (selectedCrop !== 'ALL') result = result.filter(item => item.crop === selectedCrop);
    if (searchQuery.trim() !== '') {
      const q = searchQuery.toLowerCase();
      result = result.filter(item =>
        (item.farmer_name && item.farmer_name.toLowerCase().includes(q)) ||
        (item.phone && item.phone.includes(q))
      );
    }
    setFilteredDeclarations(result);
  }, [selectedDistrict, selectedCrop, searchQuery, declarations]);

  const groupedDeclarations = React.useMemo(() => {
    const grouped = [];
    const groups = {};
    filteredDeclarations.forEach(item => {
      const key = `${item.farmer_name}_${item.phone || ''}`;
      if (!groups[key]) {
        groups[key] = {
          key, farmer_name: item.farmer_name, phone: item.phone,
          district: item.district, taluk: item.taluk,
          total_area: 0, avg_trust: 0, declarations: []
        };
        grouped.push(groups[key]);
      }
      groups[key].declarations.push(item);
      groups[key].total_area += item.area_acres;
      groups[key].avg_trust += item.trust_score || 0;
    });
    grouped.forEach(g => { g.avg_trust = g.declarations.length > 0 ? (g.avg_trust / g.declarations.length) : 0; });
    return grouped;
  }, [filteredDeclarations]);

  const handleAudit = (id, status) => {
    const token = localStorage.getItem('auth_token');
    fetch(`${API}/farmer/declaration/${id}/verify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({ status })
    })
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          setDeclarations(prev => prev.map(d =>
            d.id === id ? { ...d, satellite_status: status, trust_score: status === 'verified' ? 1.0 : 0.0 } : d
          ));
        }
      })
      .catch(err => console.error("Error executing audit verification", err));
  };

  const handleExportCSV = () => {
    logAudit('EXPORT_CSV', `${filteredDeclarations.length} records exported`);

    if (filteredDeclarations.length === 0) {
      toast.error('No data available to export');
      return;
    }

    const headers = ['Farmer Name', 'Phone', 'District', 'Taluk', 'Crop', 'Acreage', 'Trust Score', 'Satellite Status'];
    const rows = filteredDeclarations.map(row => [
      `"${row.farmer_name}"`, `"${row.phone}"`, `"${row.district}"`, `"${row.taluk || ''}"`,
      `"${row.crop}"`, row.area_acres.toFixed(1), (row.trust_score * 100).toFixed(0) + '%',
      `"${row.satellite_status || 'pending'}"`
    ]);
    const csvContent = [headers.join(','), ...rows.map(r => r.join(','))].join('\n');

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);
    link.setAttribute('href', url);
    link.setAttribute('download', `kisanmitra_registry_${new Date().toISOString().split('T')[0]}.csv`);
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);

    toast.success('Registry export downloaded successfully!');
  };

  return (
    <div className="space-y-6">
      <Card className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div className="space-y-1">
          <h2 className="text-sm font-bold uppercase tracking-wider flex items-center gap-2 text-slate-900 dark:text-white">
            <Users className="h-4 w-4 text-emerald-500" /> Farmers Declaration Registry
          </h2>
          <p className="text-xs text-slate-600">
            Live database registry of current crop declarations and satellite validation scores.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-4 w-full md:w-auto">
          <input
            type="text"
            placeholder="Search by name or phone..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="bg-white border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-800 focus:outline-none focus:border-slate-400 rounded-xl dark:bg-slate-900/60 dark:border-white/10 dark:text-slate-200 w-44"
          />

          <div className="flex items-center gap-2">
            <Filter className="h-3.5 w-3.5 text-slate-600" />
            <select value={selectedDistrict} onChange={(e) => setSelectedDistrict(e.target.value)}
              className="bg-white border border-slate-200 px-3 py-1.5 text-xs font-bold text-slate-800 focus:outline-none focus:border-slate-400 rounded-xl cursor-pointer dark:bg-slate-900/60 dark:border-white/10 dark:text-slate-200">
              {districts.map(d => <option key={d} value={d}>{d === 'ALL' ? 'ALL DISTRICTS' : d.toUpperCase()}</option>)}
            </select>
          </div>

          <select value={selectedCrop} onChange={(e) => setSelectedCrop(e.target.value)}
            className="bg-white border border-slate-200 px-3 py-1.5 text-xs font-bold text-slate-800 focus:outline-none focus:border-slate-400 rounded-xl cursor-pointer dark:bg-slate-900/60 dark:border-white/10 dark:text-slate-200">
            {crops.map(c => <option key={c} value={c}>{c === 'ALL' ? 'ALL CROPS' : c.toUpperCase()}</option>)}
          </select>

          <button onClick={fetchDeclarations} title="Refresh Data"
            className="p-2 border border-slate-200 hover:bg-slate-50 rounded-xl transition-colors text-slate-500 dark:border-white/10 dark:text-slate-400 dark:hover:bg-white/5">
            <RefreshCw className="h-3.5 w-3.5" />
          </button>

          <button onClick={handleExportCSV} title="Download CSV"
            className="hidden md:flex p-2 items-center gap-1.5 border border-slate-200 hover:bg-slate-50 rounded-xl transition-colors text-[10px] font-bold text-slate-500 uppercase tracking-wider dark:border-white/10 dark:text-slate-400 dark:hover:bg-white/5">
            <Download className="h-3.5 w-3.5" />
            <span>Export CSV</span>
          </button>
        </div>
      </Card>

      <div className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden flex flex-col justify-between min-h-[400px] dark:bg-white/5 dark:backdrop-blur-xl dark:border-white/10">
        {loading ? (
          <div className="flex-1 flex items-center justify-center text-xs font-bold text-slate-400 animate-pulse">
            Ingesting Farmers Declaration logs...
          </div>
        ) : filteredDeclarations.length === 0 ? (
          <div className="flex-1 flex items-center justify-center text-xs font-bold text-slate-400">
            No declarations matched the select criteria.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-[850px] lg:w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-slate-200 dark:border-white/5 bg-slate-50/55 dark:bg-slate-950/20 font-bold uppercase text-[9px] text-slate-700 dark:text-slate-400 tracking-wider">
                  <th className="p-3 w-8"></th>
                  <th className="p-3">Farmer Name</th>
                  <th className="p-3">Phone</th>
                  <th className="p-3">District</th>
                  <th className="p-3">Taluk</th>
                  <th className="p-3">Registered Crops</th>
                  <th className="p-3 text-right">Total Acreage</th>
                  <th className="p-3 text-right">Avg Trust</th>
                  <th className="p-3 text-center">Declarations</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-white/5 text-slate-700 dark:text-slate-400">
                {groupedDeclarations.map((group) => {
                  const isExpanded = expandedFarmers.has(group.key);
                  return (
                    <React.Fragment key={group.key}>
                      <tr className="hover:bg-slate-50/50 dark:hover:bg-white/[0.02] transition-colors border-b border-slate-100 dark:border-white/5">
                        <td className="p-3 text-center w-8">
                          <button onClick={() => toggleExpandFarmer(group.key)}
                            className="p-1 rounded hover:bg-slate-100 dark:hover:bg-white/5 text-slate-500 transition-colors">
                            {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                          </button>
                        </td>
                        <td className="p-3 font-bold text-slate-900 dark:text-white">{group.farmer_name}</td>
                        <td className="p-3 font-mono select-none">
                          <div className="flex items-center gap-1.5 justify-between max-w-[140px]">
                            <span className={revealedPhones.has(group.key) ? "text-slate-800 dark:text-slate-200" : "text-slate-500 dark:text-slate-500"}>
                              {revealedPhones.has(group.key) ? group.phone : (group.phone ? group.phone.substring(0, 5) + 'XXXXX' : '—')}
                            </span>
                            <button onClick={() => toggleRevealPhone(group.key)}
                              className="text-[9px] font-bold uppercase tracking-wider px-2 py-0.5 rounded border border-slate-200 hover:border-emerald-500 bg-slate-50 hover:bg-emerald-50 text-slate-500 hover:text-emerald-700 dark:bg-white/5 dark:border-white/10 dark:text-slate-400 dark:hover:bg-emerald-500/10 dark:hover:text-emerald-400 transition-all cursor-pointer">
                              {revealedPhones.has(group.key) ? "Hide" : "Reveal"}
                            </button>
                          </div>
                        </td>
                        <td className="p-3 font-semibold text-slate-800 dark:text-slate-300">{group.district}</td>
                        <td className="p-3 font-medium text-slate-700 dark:text-slate-500">{group.taluk || '—'}</td>
                        <td className="p-3 font-bold text-slate-600 dark:text-slate-300">
                          {Array.from(new Set(group.declarations.map(d => d.crop))).join(', ')}
                        </td>
                        <td className="p-3 text-right font-mono font-bold text-slate-900 dark:text-white">{group.total_area.toFixed(1)} ac</td>
                        <td className="p-3 text-right font-mono font-bold text-emerald-600 dark:text-emerald-400">
                          {(group.avg_trust * 100).toFixed(0)}%
                        </td>
                        <td className="p-3 text-center">
                          <span className="bg-slate-100 text-slate-700 dark:bg-white/10 dark:text-slate-300 px-2 py-0.5 rounded-lg text-[9px] font-bold">
                            {group.declarations.length} Crop{group.declarations.length > 1 ? 's' : ''}
                          </span>
                        </td>
                      </tr>
                      {isExpanded && (
                        <tr>
                          <td colSpan="9" className="p-4 bg-slate-50/50 dark:bg-white/[0.01] border-b border-slate-200 dark:border-white/5">
                            <div className="rounded-xl border border-slate-200 dark:border-white/10 bg-white dark:bg-slate-950/40 p-3 shadow-inner">
                              <h4 className="text-[10px] font-extrabold uppercase tracking-wider text-slate-500 mb-2 border-b border-slate-100 dark:border-white/5 pb-1">
                                Survey Ingress Records for {group.farmer_name}
                              </h4>
                              <table className="w-full text-left text-xs border-collapse">
                                <thead>
                                  <tr className="border-b border-slate-200 dark:border-white/5 font-bold uppercase text-[8px] text-slate-500 tracking-wider">
                                    <th className="p-2">Crop</th>
                                    <th className="p-2">Taluk</th>
                                    <th className="p-2 text-right">Acreage</th>
                                    <th className="p-2 text-right">Trust Score</th>
                                    <th className="p-2 text-center">Satellite Status</th>
                                    <th className="p-2 text-center">Actions</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {group.declarations.map((decl) => (
                                    <tr key={decl.id} className="border-b border-slate-100 dark:border-white/5 last:border-none">
                                      <td className="p-2 font-bold text-slate-800 dark:text-slate-300">{decl.crop}</td>
                                      <td className="p-2 font-medium text-slate-600 dark:text-slate-500">{decl.taluk || '—'}</td>
                                      <td className="p-2 text-right font-mono font-bold text-slate-900 dark:text-white">{decl.area_acres.toFixed(1)} ac</td>
                                      <td className="p-2 text-right font-mono font-bold text-emerald-600 dark:text-emerald-400">
                                        {((decl.trust_score || 0) * 100).toFixed(0)}%
                                      </td>
                                      <td className="p-2 text-center">{getStatusBadge(decl.satellite_status)}</td>
                                      <td className="p-2 text-center">
                                        <div className="flex items-center justify-center gap-1.5">
                                          {decl.satellite_status === 'pending' || !decl.satellite_status ? (
                                            <>
                                              <button onClick={() => handleAudit(decl.id, 'verified')}
                                                className="bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-500 border border-emerald-500/30 px-2 py-0.5 rounded text-[8px] font-black uppercase transition-colors">
                                                Approve
                                              </button>
                                              <button onClick={() => handleAudit(decl.id, 'failed')}
                                                className="bg-red-500/10 hover:bg-red-500/20 text-red-500 border border-red-500/30 px-2 py-0.5 rounded text-[8px] font-black uppercase transition-colors">
                                                Reject
                                              </button>
                                            </>
                                          ) : (
                                            <span className="text-[8px] text-slate-500 dark:text-slate-400 font-bold font-mono uppercase">Audited</span>
                                          )}
                                          <button onClick={() => handleDeleteDeclaration(decl.id, decl.crop)}
                                            title="Delete entry from database"
                                            className="p-1 rounded border border-red-500/30 bg-red-500/10 hover:bg-red-500/20 text-red-500 transition-colors cursor-pointer">
                                            <Trash2 className="h-3 w-3" />
                                          </button>
                                        </div>
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        <div className="bg-slate-50 border-t border-slate-200 dark:bg-white/[0.02] dark:border-white/5 p-4 text-[10px] font-mono font-bold text-slate-600 flex items-center justify-between">
          <span>SHOWING {filteredDeclarations.length} RECORDS OF {declarations.length} LOGGED</span>
          <span>DATABASE DIRECT CHANNEL VERIFIED</span>
        </div>
      </div>
    </div>
  );
}
