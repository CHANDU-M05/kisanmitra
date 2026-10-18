// src/App.jsx
import React, { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import ProtectedRoute from './components/ProtectedRoute';
// TerminalView is the landing route — kept eager so the first paint needs no
// extra chunk round-trip. Every other view is code-split into its own chunk
// and fetched only when the farmer navigates to it.
import TerminalView from './pages/TerminalView';

const Login = lazy(() => import('./pages/Login'));
const InsightsView = lazy(() => import('./pages/InsightsView'));
const AdvisoryView = lazy(() => import('./pages/AdvisoryView'));
const WeatherView = lazy(() => import('./pages/WeatherView'));
const DeclareView = lazy(() => import('./pages/DeclareView'));
const FarmersView = lazy(() => import('./pages/FarmersView'));
const BotMonitorView = lazy(() => import('./pages/BotMonitorView'));
const SettingsView = lazy(() => import('./pages/SettingsView'));

function RouteFallback() {
  return (
    <div className="flex items-center justify-center min-h-[50vh]" role="status" aria-live="polite">
      <div className="animate-spin h-8 w-8 border-4 border-green-600 border-t-transparent rounded-full" />
      <span className="sr-only">Loading…</span>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Public Login */}
        <Route path="/login" element={<Suspense fallback={<RouteFallback />}><Login /></Suspense>} />

        {/* Dashboard Shell (Public by default) */}
        <Route path="/" element={<Layout />}>
          {/* Default Route */}
          <Route index element={<Navigate to="/terminal" replace />} />

          {/* Public Views */}
          <Route path="terminal" element={<TerminalView />} />
          <Route path="insights" element={<Suspense fallback={<RouteFallback />}><InsightsView /></Suspense>} />
          <Route path="farmer" element={<Suspense fallback={<RouteFallback />}><AdvisoryView /></Suspense>} />
          <Route path="weather" element={<Suspense fallback={<RouteFallback />}><WeatherView /></Suspense>} />
          <Route path="declare" element={<Suspense fallback={<RouteFallback />}><DeclareView /></Suspense>} />

          {/* Protected Admin Views */}
          <Route
            path="admin"
            element={
              <ProtectedRoute>
                <Suspense fallback={<RouteFallback />}><FarmersView /></Suspense>
              </ProtectedRoute>
            }
          />
          <Route
            path="bot-monitor"
            element={
              <ProtectedRoute>
                <Suspense fallback={<RouteFallback />}><BotMonitorView /></Suspense>
              </ProtectedRoute>
            }
          />
          <Route
            path="settings"
            element={
              <ProtectedRoute>
                <Suspense fallback={<RouteFallback />}><SettingsView /></Suspense>
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
