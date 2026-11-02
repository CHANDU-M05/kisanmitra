// frontend/tests/session.test.mjs — admin session-expiry (401) handling.
// Run with: npm test  (node --test tests/)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  isUnauthorized,
  clearSession,
  handleSessionExpired,
  resetExpiryLatch,
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
