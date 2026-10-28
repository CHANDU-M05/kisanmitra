// frontend/tests/api.test.mjs — loading-state regression suite (Oct-2026 sweep).
// Covers the four scenarios from the audit: cold start, rejected request,
// timeout, and navigating away while a request is pending — plus the write
// no-auto-retry policy and GET de-duplication. Run with: npm test
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fetchJson, postJson, cachedGet, clearGetCache } from '../src/api.js';

const ok = (data) => ({ ok: true, status: 200, json: async () => data });

/** fetch impl that rejects when its AbortController fires (like real fetch). */
function hangingFetchUntilAbort() {
  return (url, opts) => new Promise((_res, rej) => {
    opts.signal.addEventListener('abort', () => rej(new DOMException('Aborted', 'AbortError')));
  });
}

test('cold start: first 502, retry succeeds (bounded)', async () => {
  let calls = 0;
  const fetchImpl = async () => {
    calls++;
    if (calls === 1) return { ok: false, status: 502, json: async () => ({}) };
    return ok({ hello: 'warm' });
  };
  const data = await fetchJson('u', { attempts: 2, backoffMs: 1, fetchImpl });
  assert.deepEqual(data, { hello: 'warm' });
  assert.equal(calls, 2);
});

test('rejected request: retries are bounded to exactly `attempts`', async () => {
  let calls = 0;
  const fetchImpl = async () => { calls++; throw new Error('network down'); };
  await assert.rejects(fetchJson('u', { attempts: 3, backoffMs: 1, fetchImpl }), /network down/);
  assert.equal(calls, 3, 'must not exceed the attempt budget');
});

test('timeout: a hung request settles via AbortController', async () => {
  const t0 = Date.now();
  await assert.rejects(
    fetchJson('u', { timeoutMs: 40, fetchImpl: hangingFetchUntilAbort() }),
    (e) => e.name === 'AbortError'
  );
  assert.ok(Date.now() - t0 < 2000, 'loading state settles promptly after timeout');
});

test('navigating away mid-request: abort is terminal, no retry', async () => {
  let calls = 0;
  const ext = new AbortController();
  const fetchImpl = async (url, opts) => {
    calls++;
    return new Promise((res, rej) => {
      opts.signal.addEventListener('abort', () => rej(new DOMException('Aborted', 'AbortError')));
      setTimeout(() => res(ok(1)), 5000); // would resolve long after unmount
    });
  };
  const p = fetchJson('u', { attempts: 3, backoffMs: 1, signal: ext.signal, fetchImpl });
  setTimeout(() => ext.abort(), 20);
  await assert.rejects(p, (e) => e.name === 'AbortError');
  assert.equal(calls, 1, 'cancelled fetch must not consume the retry budget');
});

test('writes: postJson NEVER auto-retries', async () => {
  let calls = 0;
  const fetchImpl = async () => { calls++; throw new Error('boom'); };
  await assert.rejects(postJson('u', {}, { fetchImpl }), /boom/);
  assert.equal(calls, 1, 'exactly one send for a non-idempotent write');

  const res = await postJson('u', {}, { fetchImpl: async () => ({ ok: false, status: 422, json: async () => ({ detail: 'bad' }) }) });
  assert.equal(res.ok, false);
  assert.equal(res.status, 422); // server "no" is returned, not retried
});

test('postJson timeout: hung write still settles', async () => {
  await assert.rejects(
    postJson('u', {}, { timeoutMs: 40, fetchImpl: hangingFetchUntilAbort() }),
    (e) => e.name === 'AbortError'
  );
});

test('cachedGet: concurrent consumers share ONE request', async () => {
  clearGetCache();
  let calls = 0;
  const fetchImpl = async () => { calls++; await new Promise(r => setTimeout(r, 10)); return ok({ n: calls }); };
  const [a, b] = await Promise.all([
    cachedGet('summary-url', { fetchImpl }),
    cachedGet('summary-url', { fetchImpl }),
  ]);
  assert.equal(calls, 1, 'in-flight dedup: no request multiplication');
  assert.deepEqual(a, b);
});

test('cachedGet: failures are not cached; success honors TTL', async () => {
  clearGetCache();
  let t = 1000;
  const now = () => t;
  let calls = 0;
  const fail = async () => { calls++; throw new Error('cold'); };
  await assert.rejects(cachedGet('s2', { fetchImpl: fail, now }));
  const good = async () => { calls++; return ok({ v: calls }); };
  assert.deepEqual(await cachedGet('s2', { fetchImpl: good, now, attempts: 1 }), { v: 2 });
  assert.deepEqual(await cachedGet('s2', { fetchImpl: good, now, attempts: 1 }), { v: 2 }, 'fresh TTL: served from cache');
  assert.equal(calls, 2);
  t += 31000; // outlive the 30s summary TTL
  assert.deepEqual(await cachedGet('s2', { fetchImpl: good, now, attempts: 1 }), { v: 3 }, 'expired TTL refetches');
});
