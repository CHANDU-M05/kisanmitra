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

// A valid, authenticated caller who lacks the right for one action (HTTP 403).
// Distinct from 401 on purpose: their session is fine and must NOT be cleared.
export const PERMISSION_DENIED_MESSAGE = 'You do not have permission to perform this action.';

/**
 * Route an authenticated mutation's HTTP response to the correct behaviour.
 * Returns true when the failure was handled here and the caller should stop
 * parsing the body, and false for a success (or any other status) the caller
 * handles itself. `storage`, `navigate` and `notify` are injected so this is
 * unit-testable with no DOM.
 *
 * - 401: expired/invalid token -> clear session + redirect (latched, so a burst
 *   of concurrent mutations still produces one notice).
 * - 403: authenticated but not permitted -> show a permission error and KEEP the
 *   session (clearing it would wrongly log a valid admin out).
 * - anything else: not our concern here (the caller decides).
 */
export function guardMutationResponse(res, { storage, navigate, notify } = {}) {
  if (!res) return false;
  if (isUnauthorized(res.status)) {
    handleSessionExpired({ storage, navigate, notify });
    return true;
  }
  if (res.status === 403) {
    if (typeof notify === 'function') notify(PERMISSION_DENIED_MESSAGE);
    return true;
  }
  return false;
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
