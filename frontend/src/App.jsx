// src/App.jsx
import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import ProtectedRoute from './components/ProtectedRoute';
import Login from './pages/Login';
import TerminalView from './pages/TerminalView';
import InsightsView from './pages/InsightsView';
import AdvisoryView from './pages/AdvisoryView';
import WeatherView from './pages/WeatherView';
import DeclareView from './pages/DeclareView';
import FarmersView from './pages/FarmersView';
import BotMonitorView from './pages/BotMonitorView';
import SettingsView from './pages/SettingsView';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Public Login */}
        <Route path="/login" element={<Login />} />
        
        {/* Dashboard Shell (Public by default) */}
        <Route path="/" element={<Layout />}>
          {/* Default Route */}
          <Route index element={<Navigate to="/terminal" replace />} />
          
          {/* Public Views */}
          <Route path="terminal" element={<TerminalView />} />
          <Route path="insights" element={<InsightsView />} />
          <Route path="farmer" element={<AdvisoryView />} />
          <Route path="weather" element={<WeatherView />} />
          <Route path="declare" element={<DeclareView />} />
          
          {/* Protected Admin Views */}
          <Route 
            path="admin" 
            element={
              <ProtectedRoute>
                <FarmersView />
              </ProtectedRoute>
            } 
          />
          <Route 
            path="bot-monitor" 
            element={
              <ProtectedRoute>
                <BotMonitorView />
              </ProtectedRoute>
            } 
          />
          <Route 
            path="settings" 
            element={
              <ProtectedRoute>
                <SettingsView />
              </ProtectedRoute>
            } 
          />
          
          {/* Catch-all Fallback */}
          <Route path="*" element={<Navigate to="/terminal" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
