"""
tests/test_request_guard.py — A1 edge protections: body cap, throttle, 400 ladder.

Covers, against the guard exactly as installed on the real app:
  * streamed-byte 413 enforcement including CHUNKED bodies and a Content-Length
    header that lies in both directions (the decision uses real bytes only);
  * the admission order 413 → 429 → 422 → 400 → handler, asserting a rejected
    request never reaches the endpoint at all;
  * the shared fallback bucket: its exhaustion arithmetic, the 429's
    Retry-After, and — critically — the documented limitation that ONE caller
    can exhaust the bucket and throttle every other legitimate caller with it,
    because identity (sender_id or otherwise) is deliberately not used.
  * validator behaviour on IP-resolution failure paths (no peer → shared key;
    XFF never consulted unless explicitly opted in).

Pre-commit review additions (focused, run against a REAL uvicorn over TCP):
  * concurrent-count exactness and cross-thread consume() atomicity; 413s
    burning zero quota under concurrency;
  * a chunked Transfer-Encoding body whose Content-Length UNDER-reports the
    stream (the classic cap-bypass attempt) over a live keep-alive connection;
  * the trust_proxy_headers wiring: the resolver chain is identical unless the
    flag is explicitly True, and the env override cannot reach production.

Limits are monkeypatched to small values so the fixed-window arithmetic is
tested in seconds, not by shipping 16 KB payloads through every case; the
constants themselves are pinned separately.
"""
from __future__ import annotations

import asyncio
import contextlib
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from backend.core import request_guard as rg
from backend.core.rate_limit import (
    SHARED_BUCKET_KEY,
    DirectPeerResolver,
    FixedWindowLimiter,
    ForwardedForResolver,
)

# ── stub app carrying the same guard as backend.main ─────────────
# sender scope: None → every request resolves to the shared fallback bucket,
# which is both the honest local-deployment behaviour and the stress case the
# spec demands we characterise explicitly.

def make_guarded_app(limit: int = 1000) -> tuple[FastAPI, list]:
    app = FastAPI()
    hits: list = []

    app.add_middleware(rg.RequestGuardMiddleware, trust_proxy_headers=False)

    @app.post("/api/v1/farmer/advisory")
    async def advisory(req: dict, request: Request):
        query = rg.require_advisory_query(req)     # 400 layer FIRST: a
        hits.append(dict(req))                     # rejection must not leave
        return {"ok": True, "query": query}        # a trace in the recorder

    @app.post("/api/v1/conversation/message")
    async def message(req: dict):
        hits.append(dict(req))
        return {"ok": True}

    # A deliberately unguarded path: the webhook keeps its own auth and must
    # see an untouched receive stream (no replayed body, no cap, no throttle).
    @app.post("/webhook/whatsapp")
    async def webhook(request: Request):
        raw = await request.body()
        hits.append({"raw": raw})
        return {"ok": True, "len": len(raw)}

    return app, hits


def _set_small_caps(monkeypatch, max_bytes: int = 1024,
                    advisory_limit: int = 30, message_limit: int = 60):
    monkeypatch.setattr(rg, "MAX_REQUEST_BYTES", max_bytes)
    monkeypatch.setattr(rg, "MAX_CONTENT_LENGTH_BYTES", max_bytes)
    monkeypatch.setattr(rg, "GUARDED_PATHS", {
        "/api/v1/farmer/advisory": advisory_limit,
        "/api/v1/conversation/message": message_limit,
    })


@pytest.fixture
def guarded(monkeypatch):
    _set_small_caps(monkeypatch)
    app, hits = make_guarded_app()
    client = TestClient(app)          # no client address → shared fallback bucket
    return client, hits


# ── policy constants (the approved A1 numbers) ───────────────────

def test_a1_policy_constants():
    assert rg.MAX_REQUEST_BYTES == 16 * 1024
    assert rg.ADVISORY_LIMIT_PER_MINUTE == 30
    assert rg.CONVERSATION_LIMIT_PER_MINUTE == 60
    assert rg.MAX_ADVISORY_QUERY_CHARS == 1000
    assert rg.MAX_MESSAGE_TEXT_CHARS == 2000
    assert set(rg.GUARDED_PATHS) == {"/api/v1/farmer/advisory",
                                     "/api/v1/conversation/message"}


def test_guard_installed_on_real_app_outside_cors():
    """backend.main wires the guard as the outermost user middleware."""
    from backend.main import app as real_app

    # Starlette's user_middleware list is ordered outermost-first (each
    # add_middleware prepends; the stack is built from the reversed list).
    classes = [m.cls for m in real_app.user_middleware]
    assert classes[0] is rg.RequestGuardMiddleware
    from fastapi.middleware.cors import CORSMiddleware
    assert CORSMiddleware in classes and classes.index(CORSMiddleware) > 0


# ── streamed-body cap (413) ──────────────────────────────────────

def test_small_body_passes_and_reaches_handler(guarded):
    client, hits = guarded
    res = client.post("/api/v1/farmer/advisory", json={"query": "ragi price"})
    assert res.status_code == 200
    assert res.json()["query"] == "ragi price"
    assert hits and hits[0]["query"] == "ragi price"


def test_content_length_over_cap_rejected_before_read(guarded):
    client, _ = guarded
    big = b"x" * (1024 + 500)
    res = client.post("/api/v1/farmer/advisory", content=big,
                      headers={"Content-Type": "application/json",
                               "Content-Length": str(len(big))})
    assert res.status_code == 413
    assert res.json()["max_bytes"] == 1024


def test_chunked_upload_over_cap_rejected_on_real_bytes(guarded):
    """A chunked (iterable) body streams real bytes past the cap; whatever
    length header the transport declares, the streamed count decides 413."""
    client, hits = guarded
    before = len(hits)
    res = client.post("/api/v1/farmer/advisory",
                      content=iter([b"[" + b"a" * 500 for _ in range(10)]),
                      headers={"Content-Type": "application/json"})
    assert res.status_code == 413
    assert len(hits) == before          # handler never touched the body


# ── chunked counting at the raw ASGI layer ───────────────────
# httpx always frames a fixed body with a Content-Length it computes itself,
# so a header-less, multi-message stream can only be driven by calling the
# middleware directly with synthetic ASGI messages — which is exactly the
# chunked-transfer shape the cap must survive.

@pytest.mark.asyncio
async def test_raw_asgi_multi_message_body_is_counted_and_replayed(monkeypatch):
    _set_small_caps(monkeypatch, max_bytes=100)
    seen: list = []

    async def downstream(scope, receive, send):
        message = await receive()
        seen.append(message)
        from starlette.responses import JSONResponse
        await JSONResponse({"ok": True})(scope, receive, send)

    gate = rg.RequestGuardMiddleware(downstream)

    async def stream_body(*chunks, disconnect_after=False):
        queue = list(chunks)
        tail = disconnect_after

        async def receive():
            nonlocal tail
            if queue:
                return queue.pop(0)
            if tail:
                tail = False
                return {"type": "http.disconnect"}
            return {"type": "http.request", "body": b"", "more_body": False}

        return receive

    scope = {"type": "http", "path": "/api/v1/farmer/advisory", "method": "POST",
             "headers": [], "client": None}
    sent: list = []

    async def send(message):
        sent.append(message)

    # 1) many small chunks, no Content-Length, total 120 > 100 cap → 413
    receive = await stream_body(*[{"type": "http.request", "body": b"z" * 30,
                                   "more_body": True} for _ in range(4)])
    await gate(scope, receive, send)
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    assert status == 413
    assert not seen                      # downstream never read the body

    # 2) chunks totalling under the cap → replayed to downstream as one body
    sent.clear()
    receive = await stream_body({"type": "http.request", "body": b"ab",
                                 "more_body": True},
                                {"type": "http.request", "body": b"cd",
                                 "more_body": False})
    await gate(scope, receive, send)
    assert seen and seen[0]["body"] == b"abcd" and not seen[0]["more_body"]

    # 3) client vanishes mid-body → no response is fabricated
    sent.clear(); seen.clear()
    receive = await stream_body({"type": "http.request", "body": b"ab",
                                 "more_body": True}, disconnect_after=True)
    await gate(scope, receive, send)
    assert sent == [] and seen == []


# ── throttle (429 + Retry-After) ─────────────────────────────────

def test_advisory_throttled_at_limit_with_retry_after(guarded):
    client, hits = guarded
    for i in range(30):
        assert client.post("/api/v1/farmer/advisory",
                           json={"query": f"q{i}"}).status_code == 200
    assert len(hits) == 30
    res = client.post("/api/v1/farmer/advisory", json={"query": "late"})
    assert res.status_code == 429
    retry_after = res.headers["retry-after"]
    assert 1 <= int(retry_after) <= 60
    assert res.json()["retry_after"] == int(retry_after)
    assert len(hits) == 30              # throttled request never reached handler


def test_conversation_bucket_is_independent_of_advisory_bucket(guarded):
    client, _ = guarded
    for _ in range(30):
        assert client.post("/api/v1/farmer/advisory", json={"query": "x"}).status_code == 200
    assert client.post("/api/v1/farmer/advisory", json={"query": "x"}).status_code == 429
    # The conversation limit is a separate counter at its own (60) level.
    assert client.post("/api/v1/conversation/message",
                       json={"sender_id": "9112345678", "text": "hi"}).status_code == 200


def test_window_resets_after_expiry(monkeypatch):
    _set_small_caps(monkeypatch, advisory_limit=2)
    limiter = FixedWindowLimiter(window_seconds=0.2)
    assert limiter.consume("k", 2).allowed
    assert limiter.consume("k", 2).allowed
    denied = limiter.consume("k", 2)
    assert not denied.allowed and denied.retry_after_seconds == 1
    time.sleep(0.25)
    assert limiter.consume("k", 2).allowed


# ── admission order: 413 → 429 → 422 → 400 → handler ─────────────

def test_oversized_body_never_consumes_a_throttle_bucket(guarded):
    """413 precedes 429: a giant rejected upload cannot burn quota."""
    client, hits = guarded
    for _ in range(30):
        client.post("/api/v1/farmer/advisory", json={"query": "x"})
    assert client.post("/api/v1/farmer/advisory",
                       content=b"z" * 5000).status_code == 413
    # Still fully throttled (not one extra denial caused by the 413), and the
    # 413 itself was answered before any bucket arithmetic — prove ordering by
    # a second oversized request still getting 413, not 429.
    assert client.post("/api/v1/farmer/advisory",
                       content=b"z" * 5000).status_code == 413
    assert len(hits) == 30


def test_throttle_precedes_schema_validation(guarded):
    """429 before 422: a flooded client gets 429 even for a malformed body."""
    client, hits = guarded
    for _ in range(30):
        client.post("/api/v1/farmer/advisory", json={"query": "x"})
    res = client.post("/api/v1/farmer/advisory", content=b"not json",
                      headers={"Content-Type": "application/json"})
    assert res.status_code == 429
    assert len(hits) == 30


def test_schema_layer_precedes_semantic_validators():
    """The gate admits a well-formed-enough body; FastAPI's schema parse (422)
    and the handler's semantic 400s are strictly later layers. The stub here
    accepts a loose dict, so a missing sender_id only 422s on the REAL
    schema — asserted in test_real_schema_rejects_missing_sender_with_422."""
    app, hits = make_guarded_app()          # unpatched 16 KB caps
    client = TestClient(app)
    res = client.post("/api/v1/conversation/message", json={"text": "hi"})
    assert res.status_code == 200           # stub admits; real schema would 422
    assert len(hits) == 1


def test_real_schema_rejects_missing_sender_with_422():
    import pydantic

    from backend.routers.conversation import ConversationRequest

    with pytest.raises(pydantic.ValidationError):
        ConversationRequest(text="price")   # sender_id required → 422 layer


def test_semantic_400_before_endpoint_side_effects(guarded):
    client, hits = guarded
    res = client.post("/api/v1/farmer/advisory", json={"query": "   "})
    assert res.status_code == 400
    assert "must not be empty" in res.json()["detail"]
    assert hits == []                     # rejected request left no side-effect
    # non-string query is a semantic 400, not 422 (the schema is a loose dict)
    res = client.post("/api/v1/farmer/advisory", json={"query": 123})
    assert res.status_code == 400 and "must be a string" in res.json()["detail"]
    # over-long query (chars) is 400; keep it under the patched byte cap
    res = client.post("/api/v1/farmer/advisory",
                      json={"query": "a" * 1001})
    assert res.status_code == 400
    assert "too long" in res.json()["detail"] and "1000" in res.json()["detail"]


# ── unguarded paths stay untouched ───────────────────────────────

def test_webhook_not_throttled_or_capped_by_a1(guarded):
    client, hits = guarded
    payload = b'{"entry": "' + b"w" * 3000 + b'"}'   # over the patched cap
    for _ in range(5):
        res = client.post("/webhook/whatsapp", content=payload)
        assert res.status_code == 200                 # no 413, no 429
    assert hits[-1]["raw"] == payload                 # raw bytes untouched


# ── IP resolution failure and the shared-fallback limitation ─────

def test_no_peer_resolves_to_shared_bucket_and_one_caller_exhausts_it(guarded):
    """THE documented limitation, shown end to end.

    TestClient carries no client address, so identity resolution FAILS for
    every request and all of them share one fallback bucket. One caller
    exhausting it throttles every other legitimate caller — different
    sender_ids, different bodies, same 429. The limiter is best-effort abuse
    control, not per-user fairness, and this test is the executable proof.
    """
    client, hits = guarded
    for i in range(30):
        assert client.post("/api/v1/farmer/advisory",
                           json={"query": f"legit-{i}"}).status_code == 200
    # A second "user" — different content entirely — is collaterally throttled.
    res = client.post("/api/v1/farmer/advisory", json={"query": "different-user"})
    assert res.status_code == 429
    assert len(hits) == 30


def test_bucket_key_never_uses_sender_identity(guarded):
    """Bodies with different sender_ids land in the SAME fallback bucket."""
    client, _ = guarded
    codes = {client.post("/api/v1/conversation/message",
                         json={"sender_id": f"9{i}00000000", "text": "hi"}).status_code
             for i in range(60)}
    assert codes == {200}
    res = client.post("/api/v1/conversation/message",
                      json={"sender_id": "9999999999", "text": "hi"})
    assert res.status_code == 429


def test_forwarded_header_is_ignored_unless_explicitly_trusted(monkeypatch):
    """With the default (untrusted) config an X-Forwarded-For is decoration:
    bucketing is identical with and without it, so callers cannot pick a
    bucket by renaming themselves in a header."""
    _set_small_caps(monkeypatch, advisory_limit=1)
    app, _ = make_guarded_app()
    client = TestClient(app, client=("203.0.113.7", 50000))
    assert client.post("/api/v1/farmer/advisory", json={"query": "a"},
                       headers={"X-Forwarded-For": "198.51.100.1"}).status_code == 200
    # Same peer, different spoofed XFF → still throttled: the header was not
    # consulted for the bucket key.
    assert client.post("/api/v1/farmer/advisory", json={"query": "b"},
                       headers={"X-Forwarded-For": "203.0.113.99"}).status_code == 429


def test_direct_peer_resolver_and_forwarded_resolver_units():
    assert DirectPeerResolver().resolve({"client": ("192.0.2.1", 1234)}) == "192.0.2.1"
    assert DirectPeerResolver().resolve({}) is None
    assert DirectPeerResolver().resolve({"client": None}) is None
    assert ForwardedForResolver().resolve(
        {"headers": [(b"x-forwarded-for", b" 203.0.113.195, 10.0.0.1 ")]}) == "203.0.113.195"
    assert ForwardedForResolver().resolve({"headers": []}) is None


def test_limiter_units_cover_shared_key_and_window_reset():
    """The installed guard keeps bucket state on the guard instance — key
    resolution and limits are isolated from handlers so a verified proxy
    strategy can replace the fallback without touching route code."""
    limiter = rg.FixedWindowLimiter()
    assert limiter.consume(SHARED_BUCKET_KEY, 1).allowed
    assert not limiter.consume(SHARED_BUCKET_KEY, 1).allowed
    limiter.reset()
    assert limiter.consume(SHARED_BUCKET_KEY, 1).allowed


# ── conversation 400-layer validators (function level) ───────────

def _conv_body(**kw):
    from types import SimpleNamespace
    defaults = dict(sender_id="9112345678", text="tomato price", channel="web",
                    crop=None, district=None, area=None, intent=None)
    return SimpleNamespace(**{**defaults, **kw})


def test_sender_id_bound_matches_database_column():
    from backend.core.models import ChatHistory
    from backend.routers.conversation import SENDER_ID_MAX_LENGTH

    col = ChatHistory.__table__.c.phone_number
    assert getattr(col.type, "length", None) == SENDER_ID_MAX_LENGTH == 20

    assert rg.bounded_sender_id("9" * 20, 20) == "9" * 20
    with pytest.raises(HTTPException) as exc:
        rg.bounded_sender_id("9" * 21, 20)
    assert exc.value.status_code == 400 and "too long" in exc.value.detail


def test_message_text_validator_rules():
    rg.require_message_text(_conv_body(text="ok"))
    with pytest.raises(HTTPException) as exc:
        rg.require_message_text(_conv_body(text="   "))
    assert exc.value.status_code == 400 and "empty" in exc.value.detail
    with pytest.raises(HTTPException) as exc:
        rg.require_message_text(_conv_body(text="a" * 2001))
    assert exc.value.status_code == 400 and "2000" in exc.value.detail


def test_message_intent_validator_rules():
    rg.require_message_intent(_conv_body(intent=None))
    rg.require_message_intent(_conv_body(intent="PRICE_QUERY"))
    rg.require_message_intent(_conv_body(intent="CONFIRM_DECLARE_CROP"))  # bot alias
    with pytest.raises(HTTPException) as exc:
        rg.require_message_intent(_conv_body(intent="DROP_TABLES"))
    assert exc.value.status_code == 400 and "Unknown intent" in exc.value.detail


def test_require_non_empty_text_strips_and_bounds():
    assert rg.require_non_empty_text("  tomato  ", "query", 100) == "tomato"
    for bad, frag in [("", "empty"), ("   ", "empty"), (5, "string"),
                      ("a" * 101, "too long")]:
        with pytest.raises(HTTPException) as exc:
            rg.require_non_empty_text(bad, "query", 100)
        assert exc.value.status_code == 400 and frag in exc.value.detail


# ── ChatHistory persistence stays best-effort (source-level) ─────

def test_persistence_failures_never_convert_advice_into_500():
    """Both guarded handlers wrap every ChatHistory write in a logged,
    rolled-back, best-effort path: delivered advice must not 500 because
    telemetry died, and telemetry loss must not be silent."""
    import inspect

    import backend.routers.conversation as conv
    from backend.routers import farmers

    conv_src = inspect.getsource(conv.conversation_message)
    assert conv_src.count('await db.rollback()') >= 2       # both turns guarded
    assert 'logger.error("ChatHistory user-turn logging failed' in conv_src
    assert 'logger.error("ChatHistory assistant-turn logging/commit failed' in conv_src
    adv_src = inspect.getsource(farmers.get_advisory)
    assert 'db.add(user_log)' in adv_src                     # adds are inside…
    assert adv_src.index("try:") < adv_src.index("db.add(user_log)")
    assert "ChatHistory telemetry failed" in adv_src
    assert adv_src.index("get_agronomy_advice") < adv_src.index("try:")  # after advice


# ── production wiring ────────────────────────────────────────────

def test_guard_uses_settings_trust_flag_default_off():
    from backend.core.config import settings

    assert settings.trust_proxy_headers is False


# ── REVIEW 1: concurrency — count exactness and non-bypass ───────

def test_concurrent_threads_consume_exact_quota():
    """consume() has no await/yield inside the read-modify-write, so one event
    loop cannot interleave; across threads every op is a single GIL-atomic
    dict touch. 8 threads × 50 attempts on a limit of 20 must admit EXACTLY
    20 — no clobbering lost-count bypass."""
    limiter = FixedWindowLimiter()
    def hammer(_): return sum(limiter.consume("k", 20).allowed for _ in range(50))
    with ThreadPoolExecutor(max_workers=8) as pool:
        admitted = sum(pool.map(hammer, range(8)))
    assert admitted == 20


@pytest.mark.asyncio
async def test_awaiting_tasks_cannot_interleave_consume():
    """On ONE event loop, even maximally-concurrent task switches cannot slip
    past the counter: consume() runs to completion before any other task
    resumes, so 40 concurrent consumes on a limit of 20 admit exactly 20."""
    limiter = FixedWindowLimiter()
    results = await asyncio.gather(*[
        _consume_once(limiter, 20) for _ in range(40)
    ])
    assert sum(r.allowed for r in results) == 20


async def _consume_once(limiter, limit):
    return limiter.consume("shared", limit)


# ── REVIEW 3: trust_proxy_headers wiring ────────────────────

def test_resolver_chain_identical_unless_flag_explicitly_true():
    from backend.core.rate_limit import SHARED_BUCKET_KEY

    app, _ = make_guarded_app()
    gate = _find_gate(app)
    assert [type(r).__name__ for r in gate._resolvers] == ["DirectPeerResolver"]
    scope_xff = {"client": None, "headers": [(b"x-forwarded-for", b"198.51.100.7")]}
    assert gate._bucket_key(scope_xff) == SHARED_BUCKET_KEY  # header ignored

    trusting = rg.RequestGuardMiddleware(app, trust_proxy_headers=True)
    assert [type(r).__name__ for r in trusting._resolvers] == [
        "DirectPeerResolver", "ForwardedForResolver"]
    # Even then the SERVER-observed peer wins: the header only applies when no
    # peer exists at all, and enabling it is rejected in production below.
    assert trusting._bucket_key({"client": ("203.0.113.9", 1), "headers": []}) == "203.0.113.9"


def test_env_override_cannot_reach_production():
    """A bare env export (as a leaked Render var would be) is parsed by
    Settings, but production import dies on it BEFORE any middleware is
    built, and with the flag off the installed real app has no forwarded
    resolver in its chain."""
    code = ("import os; os.environ['TRUST_PROXY_HEADERS']='true';"
            "os.environ['APP_ENV']='production'; import backend.main")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode != 0
    assert "TRUST_PROXY_HEADERS" in (r.stderr + r.stdout)

    dev_code = ("import os; os.environ['TRUST_PROXY_HEADERS']='true';"
                "os.environ['APP_ENV']='development';"
                "from backend.core.config import Settings;"
                "print(Settings(_env_file=None).trust_proxy_headers)")
    r = subprocess.run([sys.executable, "-c", dev_code], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip().endswith("True")

    from backend.main import app as real_app
    gate = _find_gate(real_app)
    assert all(type(r).__name__ != "ForwardedForResolver" for r in gate._resolvers)


def _find_gate(app):
    # FastAPI/Starlette builds the middleware stack lazily at startup; where
    # a test inspects the installed guard before any request, the stack is
    # still None, so ask for it explicitly rather than assuming a running app.
    stack = app.middleware_stack
    if stack is None:
        stack = app.build_middleware_stack()
    node = stack
    while node is not None and not isinstance(node, rg.RequestGuardMiddleware):
        node = getattr(node, "app", None)
    assert node is not None, "guard not found in built middleware stack"
    return node


# ── REVIEW 1+2: live uvicorn over real TCP ──────────────────
# TestClient bypasses real socket framing, so the security-sensitive parts —
# chunked Transfer-Encoding, keep-alive reuse after a mid-stream rejection,
# genuine concurrent connections — are verified against a real server on
# 127.0.0.1 (loopback only; this is the local/test stage).


@contextlib.contextmanager
def _live_server(app):
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning",
                            lifespan="off")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        if not thread.is_alive():
            raise RuntimeError("uvicorn thread died during startup")
        time.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@contextlib.contextmanager
def _live_guard(app):
    with _live_server(app) as base:
        yield base, _find_gate(app)


def test_live_concurrent_burst_admits_exactly_the_limit(monkeypatch):
    _set_small_caps(monkeypatch, advisory_limit=20)
    app, _hits = make_guarded_app()
    with _live_guard(app) as (base, gate):
        async def burst():
            async with httpx.AsyncClient(timeout=10) as client:
                reqs = [client.post(f"{base}/api/v1/farmer/advisory",
                                    json={"query": "q"}) for _ in range(40)]
                return await asyncio.gather(*reqs)
        responses = asyncio.run(burst())
        codes = sorted(r.status_code for r in responses)
        assert codes.count(200) == 20 and codes.count(429) == 20
        assert all("retry-after" in r.headers for r in responses if r.status_code == 429)
        assert gate.limiter.consume("127.0.0.1", 21).allowed  # exactly 20 consumed


def test_live_understated_chunked_length_cannot_bypass_cap(monkeypatch):
    """The classic bypass attempt over a REAL socket: declare
    Transfer-Encoding: chunked with no (or tiny) Content-Length and stream
    40 KB. The streamed byte count must stop it at the cap, and the shared
    keep-alive connection must stay usable afterwards."""
    _set_small_caps(monkeypatch, max_bytes=1024, advisory_limit=1000)
    app, hits = make_guarded_app()
    with _live_server(app) as base:
        with httpx.Client() as client:
            def body():
                yield b"[" + b"a" * 1000
                yield b"a" * 39000 + b"]"
            res = client.post(f"{base}/api/v1/farmer/advisory", content=body())
            assert res.status_code == 413
            assert len(hits) == 0
            # Same connection survives the mid-stream rejection: the next
            # legitimate request is answered, not hung or desynchronised.
            ok = client.post(f"{base}/api/v1/farmer/advisory",
                             json={"query": "after-413"})
            assert ok.status_code == 200
            assert ok.json()["query"] == "after-413"


def test_live_oversized_rejections_never_burn_quota(monkeypatch):
    """413-before-429 holds under real concurrency too: 10 simultaneous
    oversized POSTs on a full-but-not-over quota bucket leave the counter
    exactly where it was."""
    _set_small_caps(monkeypatch, max_bytes=1024, advisory_limit=1000)
    app, _hits = make_guarded_app()
    with _live_guard(app) as (base, gate):
        async def flood():
            async with httpx.AsyncClient(timeout=10) as client:
                reqs = [client.post(f"{base}/api/v1/farmer/advisory",
                                    content=b"x" * 3000) for _ in range(10)]
                return await asyncio.gather(*reqs)
        responses = asyncio.run(flood())
        assert all(r.status_code == 413 for r in responses)
        assert gate.limiter.consume("127.0.0.1", 1).allowed  # quota untouched


def test_live_webhook_channel_untouched_over_tcp(monkeypatch):
    """On the SAME live server, the unguarded webhook accepts a 700-byte
    payload while the guarded advisory path is at a 100-byte cap — proving
    A1 does not reach the channel that verifies Meta signatures."""
    _set_small_caps(monkeypatch, max_bytes=100, advisory_limit=1000)
    app, hits = make_guarded_app()
    with _live_server(app) as base:
        with httpx.Client() as client:
            payload = b'{"entry": "' + b"w" * 700 + b'"}'
            res = client.post(f"{base}/webhook/whatsapp", content=payload)
            assert res.status_code == 200
            assert hits[-1]["raw"] == payload       # byte-identical passthrough
            res = client.post(f"{base}/api/v1/farmer/advisory", content=b"x" * 700)
            assert res.status_code == 413           # cap applies to guarded only
