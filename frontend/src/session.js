// src/session.js — admin session-expiry handling.
//
// Why this exists: the Farmers Registry used to swallow an expired-token 401 as a
// generic "response is not an array" console error and render an empty table, so an
// admin with a stale (>24h) JWT saw "0 records" instead of being asked to sign in.
// The logic lives here as pure, dependency-injected functions so the 401 path is
// unit-testable under plain `node --test` (no DOM), and so every protected screen can
// reuse one correct behaviour instead of re-deriving it.

// The localStorage keys Login.jsx writes; clearing these flips ProtectedRoute's
// `role==='admin' && auth_token!==null` check and triggers the /login redirect.
export const SESSION_STORAGE_KEYS = ['auth_token', 'auth_status', 'role'];

export const SESSION_EXPIRED_MESSAGE = 'Your session has expired. Please sign in again.';

// Collapse a burst of concurrent 401s (double-clicked refresh, React StrictMode
// double-effect, several mounted <Toaster>s) into ONE notice + ONE redirect. A real
// expiry happens >24h after login, far outside this window, so it is never suppressed.
export const EXPIRY_COOLDOWN_MS = 3000;
let lastExpiryHandledAt = Number.NEGATIVE_INFINITY;

/** Test/edge helper: forget the last handled expiry so the next one shows immediately. */
export function resetExpiryLatch() {
  lastExpiryHandledAt = Number.NEGATIVE_INFINITY;
}

/** True only for an unauthenticated/expired-token response (HTTP 401). */
export function isUnauthorized(status) {
  return status === 401;
}

/** Remove every session key from the given storage. Tolerates missing keys. */
export function clearSession(storage) {
  if (!storage) return;
  for (const key of SESSION_STORAGE_KEYS) {
    try {
      storage.removeItem(key);
    } catch {
      /* a host may throw on storage access; a missing key is equivalent to cleared */
    }
  }
}

/**
 * Handle an expired/invalid admin session: clear the stale credentials, tell the
 * user, and route them to the login screen. `storage`, `navigate` and `notify` are
 * injected so this runs headless in tests and stays decoupled from React/router/toast.
 *
 * Credentials are ALWAYS cleared (any 401 means the token is no longer usable), but
 * the user-facing notice + redirect are latched for `cooldownMs` so a burst of
 * simultaneous 401s does not stack duplicate toasts or fire repeated navigations.
 * Returns the message shown, or null when the notice was suppressed as a duplicate.
 */
export function handleSessionExpired({
  storage, navigate, notify, message,
  now = () => Date.now(), cooldownMs = EXPIRY_COOLDOWN_MS,
} = {}) {
  clearSession(storage);
  const current = now();
  if (current - lastExpiryHandledAt < cooldownMs) {
    return null; // already surfaced a notice for this burst
  }
  lastExpiryHandledAt = current;
  const text = message || SESSION_EXPIRED_MESSAGE;
  if (typeof notify === 'function') notify(text);
  if (typeof navigate === 'function') navigate('/login', { replace: true });
  return text;
}
