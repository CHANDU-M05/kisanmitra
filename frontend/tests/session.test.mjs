// frontend/tests/session.test.mjs — admin session-expiry (401) handling.
// Run with: npm test  (node --test tests/)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  isUnauthorized,
  clearSession,
  handleSessionExpired,
  resetExpiryLatch,
  guardMutationResponse,
  PERMISSION_DENIED_MESSAGE,
  SESSION_STORAGE_KEYS,
  SESSION_EXPIRED_MESSAGE,
} from '../src/session.js';

// Minimal localStorage double: no DOM required, so this runs under plain node --test.
function makeStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem: (k) => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => data.set(k, v),
    removeItem: (k) => data.delete(k),
    _has: (k) => data.has(k),
  };
}

test('isUnauthorized is true only for HTTP 401', () => {
  assert.equal(isUnauthorized(401), true);
  assert.equal(isUnauthorized(200), false);
  assert.equal(isUnauthorized(403), false); // forbidden != expired: must NOT clear session
  assert.equal(isUnauthorized(422), false);
  assert.equal(isUnauthorized(500), false);
  assert.equal(isUnauthorized(undefined), false);
});

test('clearSession removes every session key Login writes', () => {
  const storage = makeStorage({ auth_token: 'jwt', auth_status: 'true', role: 'admin', keepme: 'x' });
  clearSession(storage);
  for (const key of SESSION_STORAGE_KEYS) {
    assert.equal(storage.getItem(key), null, `${key} must be cleared`);
  }
  // unrelated keys are left untouched
  assert.equal(storage.getItem('keepme'), 'x');
});

test('clearSession tolerates missing keys and a null storage', () => {
  assert.doesNotThrow(() => clearSession(makeStorage({})));
  assert.doesNotThrow(() => clearSession(null));
});

test('handleSessionExpired clears token, notifies, and routes to /login (replace)', () => {
  resetExpiryLatch();
  const storage = makeStorage({ auth_token: 'expired-jwt', role: 'admin', auth_status: 'true' });
  let notified = null;
  let nav = null;
  const text = handleSessionExpired({
    storage,
    navigate: (to, opts) => { nav = { to, opts }; },
    notify: (m) => { notified = m; },
  });

  // credentials gone -> ProtectedRoute's role/auth_token check now fails and redirects
  assert.equal(storage.getItem('auth_token'), null);
  assert.equal(storage.getItem('role'), null);
  // user sees a clear session-expired message
  assert.equal(notified, SESSION_EXPIRED_MESSAGE);
  assert.equal(text, SESSION_EXPIRED_MESSAGE);
  // routed to login with replace so Back does not return to the dead screen
  assert.equal(nav.to, '/login');
  assert.equal(nav.opts.replace, true);
});

test('handleSessionExpired accepts a custom message', () => {
  resetExpiryLatch();
  const notified = [];
  handleSessionExpired({
    storage: makeStorage({ auth_token: 'x' }),
    navigate: () => {},
    notify: (m) => notified.push(m),
    message: 'Admin session timed out',
  });
  assert.deepEqual(notified, ['Admin session timed out']);
});

test('handleSessionExpired is safe when navigate/notify/storage are absent', () => {
  resetExpiryLatch();
  assert.doesNotThrow(() => handleSessionExpired({}));
  resetExpiryLatch();
  assert.equal(handleSessionExpired({ now: () => 5000 }), SESSION_EXPIRED_MESSAGE);
});

test('a burst of concurrent 401s fires only one notice and one redirect', () => {
  resetExpiryLatch();
  let notified = 0;
  let redirected = 0;
  const base = 10_000;
  const call = (t) => handleSessionExpired({
    storage: makeStorage({ auth_token: 'x', role: 'admin' }),
    navigate: () => { redirected += 1; },
    notify: () => { notified += 1; },
    now: () => t,
  });
  assert.equal(call(base), SESSION_EXPIRED_MESSAGE);        // first: surfaced
  assert.equal(call(base + 100), null);                     // +100ms burst: suppressed
  assert.equal(call(base + 500), null);                     // +500ms burst: suppressed
  assert.equal(notified, 1);
  assert.equal(redirected, 1);
  // even when suppressed, the stale credentials were still cleared
  const s = makeStorage({ auth_token: 'x', role: 'admin' });
  handleSessionExpired({ storage: s, now: () => base + 600 });
  assert.equal(s.getItem('auth_token'), null);
});

test('the latch recovers, so a later genuine expiry is shown again', () => {
  resetExpiryLatch();
  let notified = 0;
  const notify = () => { notified += 1; };
  handleSessionExpired({ storage: makeStorage(), notify, navigate: () => {}, now: () => 0 });
  // past the cooldown window -> a fresh expiry is surfaced again
  handleSessionExpired({ storage: makeStorage(), notify, navigate: () => {}, now: () => 10_000 });
  assert.equal(notified, 2);
});

// ── guardMutationResponse: consistent 401/403 handling for admin mutations ────

test('guardMutationResponse: 401 clears the session, notifies and returns true', () => {
  resetExpiryLatch();
  const storage = makeStorage({ auth_token: 'expired-jwt', role: 'admin', auth_status: 'true' });
  let nav = null;
  let notified = null;
  const handled = guardMutationResponse(
    { status: 401 },
    { storage, navigate: (to, opts) => { nav = { to, opts }; }, notify: (m) => { notified = m; } },
  );
  assert.equal(handled, true);
  assert.equal(storage.getItem('auth_token'), null);
  assert.equal(notified, SESSION_EXPIRED_MESSAGE);
  assert.equal(nav.to, '/login');
  assert.equal(nav.opts.replace, true);
});

test('guardMutationResponse: 403 shows a permission error but KEEPS the session', () => {
  resetExpiryLatch();
  const storage = makeStorage({ auth_token: 'valid-jwt', role: 'admin', auth_status: 'true' });
  let navigated = false;
  let notified = null;
  const handled = guardMutationResponse(
    { status: 403 },
    { storage, navigate: () => { navigated = true; }, notify: (m) => { notified = m; } },
  );
  assert.equal(handled, true);
  assert.equal(notified, PERMISSION_DENIED_MESSAGE);
  assert.equal(navigated, false);                       // forbidden must not redirect
  assert.equal(storage.getItem('auth_token'), 'valid-jwt'); // and must not log out
});

test('guardMutationResponse: success status returns false and touches nothing', () => {
  resetExpiryLatch();
  const storage = makeStorage({ auth_token: 'valid-jwt', role: 'admin' });
  let notified = 0;
  for (const status of [200, 201, 204]) {
    assert.equal(guardMutationResponse({ status }, { storage, navigate: () => {}, notify: () => { notified += 1; } }), false);
  }
  assert.equal(notified, 0);
  assert.equal(storage.getItem('auth_token'), 'valid-jwt');
});

test('guardMutationResponse: generic server error returns false (caller handles) without clearing', () => {
  resetExpiryLatch();
  const storage = makeStorage({ auth_token: 'valid-jwt', role: 'admin' });
  let notified = 0;
  for (const status of [422, 500, 503]) {
    assert.equal(guardMutationResponse({ status }, { storage, navigate: () => {}, notify: () => { notified += 1; } }), false);
  }
  assert.equal(notified, 0);
  assert.equal(storage.getItem('auth_token'), 'valid-jwt');
});

test('guardMutationResponse: a missing response is safely not handled', () => {
  assert.equal(guardMutationResponse(null), false);
  assert.equal(guardMutationResponse(undefined, { storage: makeStorage() }), false);
});

test('a burst of concurrent 401 mutations still clears credentials but notifies once', () => {
  resetExpiryLatch();
  let notified = 0;
  let redirected = 0;
  // Two 401s in the same tick fall inside the cooldown window, so the notice and
  // the redirect collapse to one — yet every stale token is still cleared.
  const s1 = makeStorage({ auth_token: 'expired', role: 'admin' });
  guardMutationResponse({ status: 401 }, { storage: s1, navigate: () => { redirected += 1; }, notify: () => { notified += 1; } });
  const s2 = makeStorage({ auth_token: 'expired', role: 'admin' });
  guardMutationResponse({ status: 401 }, { storage: s2, navigate: () => { redirected += 1; }, notify: () => { notified += 1; } });
  assert.equal(notified, 1, 'second 401 within cooldown must not stack a notice');
  assert.equal(redirected, 1);
  assert.equal(s1.getItem('auth_token'), null);
  assert.equal(s2.getItem('auth_token'), null);
});
