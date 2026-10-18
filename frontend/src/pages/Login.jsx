// src/pages/Login.jsx
import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ShieldAlert, HelpCircle } from 'lucide-react';
import { toast, Toaster } from 'react-hot-toast';
import { API } from '../config';

export default function Login() {
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  const handleLogin = (e) => {
    e.preventDefault();
    setError('');

    const formData = new URLSearchParams();
    formData.append('username', username.trim());
    formData.append('password', password);

    fetch(`${API}/auth/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: formData.toString()
    })
    .then(res => {
      if (!res.ok) throw new Error('Invalid credentials');
      return res.json();
    })
    .then(data => {
      if (data.access_token) {
        localStorage.setItem('auth_token', data.access_token);
        localStorage.setItem('auth_status', 'true'); // Fallback for stale HMR
        localStorage.setItem('role', 'admin');
        navigate('/admin');
      }
    })
    .catch(err => {
      console.error(err);
      const msg = err.message.includes('429') ? err.message : 'Invalid admin username or password.';
      toast.error('Login failed');
      setError(msg);
    });
  };

  return (
    <div className="min-h-screen w-screen flex items-center justify-center bg-gradient-to-br from-slate-900 via-[#1F3864] to-slate-950 font-sans p-4 relative overflow-hidden">
      
      {/* Decorative Orbs */}
      <div className="absolute top-1/4 left-1/4 w-72 h-72 rounded-full bg-emerald-500/10 blur-[100px] pointer-events-none"></div>
      <div className="absolute bottom-1/4 right-1/4 w-80 h-80 rounded-full bg-blue-500/10 blur-[100px] pointer-events-none"></div>

      {/* Glass Container */}
      <div className="bg-white/5 backdrop-blur-xl border border-white/10 rounded-2xl p-8 max-w-sm w-full z-10 shadow-2xl space-y-6">
        
        {/* Brand */}
        <div className="text-center space-y-2">
          <div className="inline-flex h-9 w-9 bg-emerald-500 text-slate-950 items-center justify-center font-black text-sm rounded-xl shadow-lg shadow-emerald-500/20">
            KM
          </div>
          <h2 className="text-sm font-black tracking-widest text-white uppercase">
            KISANMITRA ADMIN
          </h2>
          <p className="text-xs text-slate-400 font-bold">
            Console Authentication Gate
          </p>
        </div>

        {/* Error prompt */}
        {error && (
          <div className="bg-red-500/10 border border-red-500/20 text-red-400 p-3 rounded-xl text-xs font-bold flex items-center gap-2">
            <ShieldAlert className="h-4 w-4 shrink-0 text-red-400" />
            <span>{error}</span>
          </div>
        )}

        {/* Login form */}
        <form onSubmit={handleLogin} className="space-y-4">
          <div className="space-y-1">
            <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">Admin Username</label>
            <input
              type="text"
              placeholder="e.g. admin"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              className="w-full bg-white/5 border border-white/10 text-white rounded-xl p-3 text-xs placeholder-slate-400 focus:outline-none focus:border-emerald-500 transition-all font-medium"
            />
          </div>

          <div className="space-y-1">
            <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">Password</label>
            <input
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="w-full bg-white/5 border border-white/10 text-white rounded-xl p-3 text-xs focus:outline-none focus:border-emerald-500 transition-all font-mono"
            />
          </div>

          <button
            type="submit"
            className="w-full bg-emerald-500 hover:bg-emerald-600 text-slate-950 text-xs font-black py-3 rounded-xl uppercase tracking-wider shadow-lg shadow-emerald-500/15 transition-all mt-4"
          >
            Authenticate Admin
          </button>
        </form>


      </div>
      <Toaster />
    </div>
  );
}
