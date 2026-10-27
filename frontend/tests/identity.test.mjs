// frontend/tests/identity.test.mjs — Phase 3 identity labelling rules.
// Run with: npm test  (node --test tests/)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { identityLabel, isPlatformIdentity, identityKey } from '../src/identity.js';

test('telegram platform rows render as Telegram #<id>, never as phone', () => {
  const row = { farmer_name: 'Telegram Farmer', phone: null, channel: 'telegram', sender_id: '6001122334' };
  assert.equal(identityLabel(row), 'Telegram #6001122334');
  assert.equal(isPlatformIdentity(row), true);
});

test('legacy unclassified rows keep their historic phone representation', () => {
  // telegram id stored in phone BEFORE the split: channel/sender_id are NULL —
  // must NOT be reinterpreted as a platform identity from the value alone.
  const legacy = { farmer_name: 'Telegram Farmer', phone: '1534422727', channel: null, sender_id: null };
  assert.equal(isPlatformIdentity(legacy), false);
  assert.equal(identityLabel(legacy), '1534422727');
});

test('web and whatsapp phone rows are labelled and keyed by phone', () => {
  const web = { farmer_name: 'Ganesh', phone: '9876543210', channel: null, sender_id: null };
  assert.equal(identityLabel(web), '9876543210');
  assert.equal(isPlatformIdentity(web), false);
  assert.equal(identityKey(web), 'Ganesh_9876543210');
});

test('identityKey groups platform rows by sender_id, not empty phone', () => {
  const a = { farmer_name: 'Telegram Farmer', phone: null, channel: 'telegram', sender_id: '111' };
  const b = { farmer_name: 'Telegram Farmer', phone: null, channel: 'telegram', sender_id: '222' };
  assert.notEqual(identityKey(a), identityKey(b), 'distinct senders must not merge');
  assert.equal(identityKey(a), 'Telegram Farmer_111');
});

test('missing identity falls back to em dash, never the string null', () => {
  assert.equal(identityLabel({ farmer_name: 'x', phone: null }), '—');
  assert.equal(identityLabel(null), '—');
});
