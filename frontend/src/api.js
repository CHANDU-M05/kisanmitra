/**
 * frontend/src/api.js — shared request logic for the whole dashboard.
 *
 * Why this exists (Oct-2026 loading-state sweep): every view used to hand-roll
 * `fetch(...).then(res => res.json())` with no timeout. On Render's free tier a
 * cold start holds or 502s the first requests for ~40s; a hanging promise never
 * resolves AND never rejects, so `.catch` fallbacks never ran and loading
 * spinners stayed up forever. InsightsView got a local fix first; this module
 * makes the same resilience consistent everywhere WITHOUT duplicating behavior
 * or multiplying requests:
 *
 *   - fetchJson:  AbortController timeout, bounded retry w/ backoff only for
 *                 idempotent GETs, external-abort relay (navigate-away stops
 *                 retries immediately).
 *   - postJson:   timeout but NEVER auto-retries — non-idempotent writes must
 *                 not be silently re-sent (declaration POST is an upsert, but
 *                 the policy is to let the user decide).
 *   - cachedGet:  in-flight de-dup + short TTL cache so the four screens that
 *                 all want /declarations/summary trigger ONE backend request.
 *
 * All functions accept an AbortSignal via options so effects can cancel
 * cleanly on unmount, and take an injectable `fetchImpl` for tests.
 */
// Explicit .js extension so BOTH Vite and plain `node --test` resolve it.
import { API } from './config.js';

export const DEFAULT_TIMEOUT_MS = 15000;
export const DEFAULT_RETRY_BACKOFF_MS = 4000;
export const SUMMARY_TTL_MS = 30000;

export function apiUrl(path) {
  return `${API}${path}`;
}

/**
 * GET a JSON URL with timeout + bounded retry.
 * options: { attempts=1, timeoutMs, signal, fetchImpl, backoffMs }
 * Throws on final failure; an external abort is terminal (no retry).
 */
export async function fetchJson(url, options = {}) {
  const {
    attempts = 1,
    timeoutMs = DEFAULT_TIMEOUT_MS,
    backoffMs = DEFAULT_RETRY_BACKOFF_MS,
    signal = null,
    fetchImpl = null,
  } = options;
  const doFetch = fetchImpl || ((u, o) => fetch(u, o));

  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');

  let lastErr;
  for (let i = 0; i < attempts; i++) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    const relay = () => ctrl.abort();
    if (signal) signal.addEventListener('abort', relay, { once: true });
    try {
      const res = await doFetch(url, { signal: ctrl.signal });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      // Navigation-away is terminal: surface immediately, never retry.
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      lastErr = err;
      if (i < attempts - 1) {
        await new Promise(r => setTimeout(r, backoffMs * (i + 1)));
      }
    } finally {
      clearTimeout(timer);
      if (signal) signal.removeEventListener('abort', relay);
    }
  }
  throw lastErr;
}

/**
 * POST JSON with a timeout but NO automatic retry — writes are not
 * idempotent by policy. Resolves { ok, status, data }; throws only on
 * network failure/timeout so the caller can distinguish "server said no"
 * from "we never got an answer".
 */
export async function postJson(url, body, options = {}) {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, signal = null, fetchImpl = null } = options;
  const doFetch = fetchImpl || ((u, o) => fetch(u, o));

  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  const relay = () => ctrl.abort();
  if (signal) signal.addEventListener('abort', relay, { once: true });
  try {
    const res = await doFetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });
    let data = null;
    try { data = await res.json(); } catch { /* non-JSON error body is fine */ }
    return { ok: res.ok, status: res.status, data };
  } finally {
    clearTimeout(timer);
    if (signal) signal.removeEventListener('abort', relay);
  }
}

// ── GET de-dup cache ───────────────────────────────────────────────────────
// key -> { promise, at, ok }  Failures are NOT cached; in-flight duplicates
// share one real request.
const _inflight = new Map();

export function cachedGet(url, options = {}) {
  const { ttlMs = SUMMARY_TTL_MS, signal: _callerSignal, ...fetchOpts } = options;
  // NOTE: the caller's abort signal is deliberately NOT relayed into the
  // shared request — the de-duped fetch belongs to the cache, not to one
  // consumer; unmounting one view must not abort another's in-flight data.
  // Callers guard themselves with their own cancelled flags.
  const now = typeof fetchOpts.now === 'function' ? fetchOpts.now() : Date.now();
  const entry = _inflight.get(url);
  if (entry) {
    if (!entry.settled) return entry.promise;          // de-dup in-flight
    if (entry.ok && (now - entry.at) < ttlMs) return entry.promise; // fresh cache
  }
  const record = { settled: false, ok: false, at: 0, promise: null };
  record.promise = fetchJson(url, fetchOpts)
    .then(data => {
      record.settled = true; record.ok = true; record.at = typeof fetchOpts.now === 'function' ? fetchOpts.now() : Date.now();
      return data;
    })
    .catch(err => {
      record.settled = true; record.ok = false;
      _inflight.delete(url); // never cache failures — allow immediate retry
      throw err;
    });
  _inflight.set(url, record);
  return record.promise;
}

/** Test/maintenance hook: drop all cached entries. */
export function clearGetCache() { _inflight.clear(); }
