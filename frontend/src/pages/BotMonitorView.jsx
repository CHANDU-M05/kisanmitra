// src/pages/BotMonitorView.jsx
import React, { useState, useEffect } from 'react';
import { MessageSquare, Heart, CheckCircle, ThumbsUp, ThumbsDown, MessageCircle, AlertCircle, ShieldAlert } from 'lucide-react';
import Card from '../components/ui/Card';
import { API } from '../config';

export default function BotMonitorView() {
  const [loading, setLoading] = useState(true);
  const [metrics, setMetrics] = useState({
    total_interactions: 0,
    engagement_rate: 0,
    accuracy_score: 0,
    failure_hotspots: []
  });
  const [chatLogs, setChatLogs] = useState([]);

  const fetchBotMonitorData = () => {
    setLoading(true);
    const token = localStorage.getItem('auth_token');

    fetch(`${API}/analytics/rag-health`, { headers: { 'Authorization': `Bearer ${token}` } })
      .then(res => res.json())
      .then(data => {
        if (data && typeof data === 'object' && !data.detail) {
          setMetrics(data);
        } else {
          console.error("Invalid RAG health metrics response:", data);
        }
      })
      .catch(err => console.error("Error fetching RAG stats", err));

    fetch(`${API}/analytics/bot/history?limit=30`, { headers: { 'Authorization': `Bearer ${token}` } })
      .then(res => res.json())
      .then(logs => {
        if (Array.isArray(logs)) {
          setChatLogs(logs);
        } else {
          console.error("Chat logs response is not an array:", logs);
        }
        setLoading(false);
      })
      .catch(err => {
        console.error("Error fetching chat logs", err);
        setLoading(false);
      });
  };

  useEffect(() => {
    fetchBotMonitorData();
    const interval = setInterval(fetchBotMonitorData, 10000);
    return () => clearInterval(interval);
  }, []);

  // Was recomputed with Math.max(...) inside every .map() iteration below
  // (O(n²) over the hotspot list on every render). Hoisted to run once.
  const maxHotspotCount = metrics.failure_hotspots.length > 0
    ? Math.max(...metrics.failure_hotspots.map(h => h.count))
    : 1;

  return (
    <div className="space-y-6">
      <Card className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div className="space-y-1">
          <h2 className="text-sm font-bold uppercase tracking-wider flex items-center gap-2 text-slate-900 dark:text-white">
            <MessageSquare className="h-4 w-4 text-emerald-500" /> WhatsApp Bot Monitor &amp; RAG Analytics
          </h2>
          <p className="text-xs text-slate-600">
            Real-time intent parsing transcripts, RAG accuracy ratings, and failure hotspots.
          </p>
        </div>

        <button
          onClick={fetchBotMonitorData}
          className="bg-slate-900 hover:bg-slate-800 dark:bg-emerald-500 dark:text-slate-950 dark:hover:bg-emerald-600 text-white text-xs font-bold py-2.5 px-4 rounded-xl uppercase tracking-wider shadow-sm transition-all self-stretch sm:self-auto"
        >
          Refresh Feed
        </button>
      </Card>

      {loading ? (
        <div className="h-64 bg-white border border-slate-200 rounded-2xl flex items-center justify-center text-xs font-bold text-slate-400 animate-pulse shadow-sm dark:bg-white/5 dark:border-white/10 dark:text-slate-500">
          Loading live conversation streams...
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <Card className="flex items-center gap-4">
              <div className="h-10 w-10 bg-blue-50 text-blue-600 dark:bg-blue-500/10 dark:text-blue-400 rounded-xl flex items-center justify-center font-bold">
                <MessageCircle className="h-5 w-5" />
              </div>
              <div className="flex flex-col">
                <span className="text-[10px] font-bold text-slate-700 uppercase tracking-widest">Interactions Logged</span>
                <span className="text-2xl font-black text-slate-900 dark:text-white">{metrics.total_interactions} Chats</span>
              </div>
            </Card>

            <Card className="flex items-center gap-4">
              <div className="h-10 w-10 bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400 rounded-xl flex items-center justify-center font-bold">
                <Heart className="h-5 w-5" />
              </div>
              <div className="flex flex-col">
                <span className="text-[10px] font-bold text-slate-700 uppercase tracking-widest">Engagement Rate</span>
                {metrics.total_interactions < 20 ? (
                  <>
                    <span className="text-sm font-bold text-slate-700 dark:text-slate-300 mt-1">Not enough data yet</span>
                    <span className="text-[9px] font-mono text-slate-500 dark:text-slate-500 mt-0.5">Needs 20+ chats to compute</span>
                  </>
                ) : (
                  <span className="text-2xl font-black text-slate-900 dark:text-white">{metrics.engagement_rate}%</span>
                )}
              </div>
            </Card>

            <Card className="flex items-center gap-4">
              <div className="h-10 w-10 bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-400 rounded-xl flex items-center justify-center font-bold">
                <CheckCircle className="h-5 w-5" />
              </div>
              <div className="flex flex-col">
                <span className="text-[10px] font-bold text-slate-700 uppercase tracking-widest">RAG Accuracy Score</span>
                {metrics.total_interactions === 0 ? (
                  <>
                    <span className="text-sm font-bold text-slate-700 dark:text-slate-300 mt-1">Awaiting feedback</span>
                    <span className="text-[9px] font-mono text-slate-500 dark:text-slate-500 mt-0.5">No 👍 / 👎 responses logged</span>
                  </>
                ) : (
                  <span className="text-2xl font-black text-slate-900 dark:text-white">{metrics.accuracy_score}%</span>
                )}
              </div>
            </Card>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-10 gap-6">
            <Card className="lg:col-span-6 flex flex-col h-[500px]">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-900 dark:text-white flex items-center gap-1.5 border-b border-slate-100 dark:border-white/5 pb-3 mb-4 shrink-0">
                Conversation Transcript Stream
              </h3>

              <div className="flex-1 overflow-y-auto space-y-3.5 pr-2">
                {chatLogs.length === 0 ? (
                  <div className="h-full flex items-center justify-center text-xs font-bold text-slate-600">
                    No active messages found in the database logs.
                  </div>
                ) : (
                  chatLogs.map((log) => {
                    const isAssistant = log.role === 'assistant';
                    return (
                      <div
                        key={log.id}
                        className={`flex flex-col max-w-[85%] p-3 rounded-2xl border text-xs shadow-sm transition-all ${
                          isAssistant
                            ? 'bg-slate-50 border-slate-200 dark:bg-white/[0.02] dark:border-white/5 self-start mr-auto rounded-tl-none'
                            : 'bg-emerald-50 border-emerald-200 dark:bg-emerald-500/10 dark:border-emerald-500/20 self-end ml-auto rounded-tr-none text-slate-950 dark:text-slate-300'
                        }`}
                      >
                        <div className="flex justify-between items-center text-[10px] font-bold text-slate-600 dark:text-slate-500 mb-1.5 font-mono">
                          <span>{isAssistant ? '🔮 ADVISORY BOT' : `📱 ${log.phone_number}`}</span>
                          <div className="flex items-center gap-2">
                            {log.intent_category && (
                              <span className="bg-slate-200/50 text-slate-700 dark:bg-white/5 dark:text-slate-300 px-1.5 py-0.5 rounded text-[8px] uppercase font-bold">
                                {log.intent_category}
                              </span>
                            )}
                            <span>{new Date(log.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                          </div>
                        </div>

                        <p className="leading-relaxed whitespace-pre-wrap text-slate-900 dark:text-slate-100">{log.message_content}</p>

                        {isAssistant && log.feedback_score !== null && (
                          <div className="mt-2 pt-1.5 border-t border-slate-200/60 dark:border-white/5 flex items-center gap-1 text-[9px] font-bold uppercase font-mono text-slate-600">
                            <span>Feedback:</span>
                            {log.feedback_score === 1 ? (
                              <span className="text-emerald-600 dark:text-emerald-400 flex items-center gap-0.5"><ThumbsUp className="h-3 w-3" /> Positive</span>
                            ) : (
                              <span className="text-red-500 dark:text-red-400 flex items-center gap-0.5"><ThumbsDown className="h-3 w-3" /> Unresolved</span>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })
                )}
              </div>
            </Card>

            <Card className="lg:col-span-4 flex flex-col justify-between h-[500px]">
              <div className="space-y-4">
                <div className="border-b border-slate-100 dark:border-white/5 pb-3">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-900 dark:text-white flex items-center gap-1.5">
                    <ShieldAlert className="h-4 w-4 text-red-500" /> Search Failure Hotspots
                  </h3>
                  <p className="text-[11px] text-slate-600 dark:text-slate-500 mt-1 leading-relaxed">
                    Identified topics where farmers flagged the bot's response as incomplete.
                  </p>
                </div>

                <div className="space-y-3 font-mono text-xs text-slate-800 dark:text-slate-300">
                  {metrics.failure_hotspots.length === 0 ? (
                    <div className="py-8 text-center font-sans font-bold text-slate-600 dark:text-slate-500">
                      No unresolved hotspots registered!
                    </div>
                  ) : (
                    metrics.failure_hotspots.map((hot, idx) => (
                      <div key={idx} className="space-y-1.5">
                        <div className="flex justify-between text-[11px] font-bold">
                          <span className="text-slate-800 dark:text-slate-300 uppercase">{hot.intent || 'UNCATEGORIZED'}</span>
                          <span className="text-red-500 dark:text-red-400">{hot.count} FLAGS</span>
                        </div>
                        <div className="w-full h-1.5 bg-slate-100 dark:bg-slate-900 rounded-lg overflow-hidden">
                          <div className="h-full bg-red-400 transition-all" style={{ width: `${Math.min((hot.count / maxHotspotCount) * 100, 100)}%` }} />
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>

              <div className="bg-slate-50 border border-slate-200 dark:bg-white/[0.02] dark:border-white/5 p-4 rounded-2xl flex items-start gap-2.5">
                <AlertCircle className="h-4 w-4 text-slate-600 dark:text-slate-500 shrink-0 mt-0.5" />
                <p className="text-[10px] leading-relaxed text-slate-600 dark:text-slate-500">
                  Transcripts list incoming WhatsApp API hooks directly. Use these failure hotspots to upload target knowledge documents in system settings.
                </p>
              </div>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
