import React, { useState, useEffect } from 'react';
import { fetchRAGHealth } from '../services/api';

const RAGHealthDashboard = () => {
  const [metrics, setMetrics] = useState(null);
  const [error, setError] = useState(false);

  const loadMetrics = async () => {
    try {
      const data = await fetchRAGHealth();
      setMetrics(data);
      setError(false);
    } catch (e) {
      setError(true);
    }
  };

  useEffect(() => {
    loadMetrics();
    const interval = setInterval(loadMetrics, 30000); // Poll every 30s
    return () => clearInterval(interval);
  }, []);

  if (!metrics) return <div className="text-secondary">Loading Health Metrics...</div>;

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '20px', marginTop: '24px' }}>
      {/* Card 1: Total */}
      <div className="glass-panel" style={{ padding: '20px' }}>
        <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', fontWeight: '600', textTransform: 'uppercase' }}>Total Interactions</div>
        <div style={{ fontSize: '2rem', fontWeight: '800', marginTop: '8px' }}>{metrics.total_interactions}</div>
        <div style={{ color: 'var(--success)', fontSize: '0.8rem', marginTop: '4px' }}>Live Feedback Active</div>
      </div>

      {/* Card 2: Engagement */}
      <div className="glass-panel" style={{ padding: '20px' }}>
        <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', fontWeight: '600', textTransform: 'uppercase' }}>Engagement Rate</div>
        <div style={{ fontSize: '2rem', fontWeight: '800', marginTop: '8px' }}>{metrics.engagement_rate}%</div>
        <div className="progress-bar-bg" style={{ height: '4px', background: 'rgba(255,255,255,0.1)', marginTop: '12px', borderRadius: '2px' }}>
          <div style={{ width: `${metrics.engagement_rate}%`, height: '100%', background: 'var(--accent-primary)', borderRadius: '2px' }} />
        </div>
      </div>

      {/* Card 3: Accuracy */}
      <div className="glass-panel" style={{ padding: '20px' }}>
        <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', fontWeight: '600', textTransform: 'uppercase' }}>RAG Accuracy</div>
        <div style={{ fontSize: '2rem', fontWeight: '800', marginTop: '8px', color: metrics.accuracy_score > 80 ? 'var(--success)' : 'var(--warning)' }}>
          {metrics.accuracy_score}%
        </div>
        <div style={{ fontSize: '0.7rem', marginTop: '4px' }}>Target: 85% Benchmark</div>
      </div>

      {/* Card 4: Hotspots */}
      <div className="glass-panel" style={{ padding: '20px' }}>
        <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', fontWeight: '600', textTransform: 'uppercase' }}>Failure Hotspots</div>
        <div style={{ marginTop: '8px' }}>
          {metrics.failure_hotspots.length > 0 ? metrics.failure_hotspots.map((h, i) => (
            <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.9rem', marginBottom: '4px' }}>
              <span style={{ color: 'var(--text-primary)' }}>{h.intent}</span>
              <span style={{ color: 'var(--danger)', fontWeight: '700' }}>{h.count} ✗</span>
            </div>
          )) : <div style={{ fontSize: '0.8rem', color: 'var(--success)' }}>No failures detected</div>}
        </div>
      </div>
    </div>
  );
};

export default RAGHealthDashboard;
