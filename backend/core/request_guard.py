"""
backend/core/request_guard.py — Body-size and throttle gate for shared endpoints.

An ASGI middleware installed OUTSIDE the CORS middleware (see
install_request_guard) so that every request to a guarded path passes the size
and frequency checks *before* anything else touches it. The admission order
is deliberate and is covered by tests:

  413 oversized body  →  429 throttled  →  422 schema parse (FastAPI)
                     →  400 semantic input (handler validators)  →  advice

Nothing is read, parsed, persisted or billed for a request the gate refuses,
and the gate covers ONLY the guarded paths below. The 16 KB cap is enforced
against the BYTES ACTUALLY STREAMED, not just the Content-Length header: a
chunked request can lie about its length in either direction, so we count
real bytes and stop at the cap (the header is consulted only to REJECT
impossible declarations early, never to accept or to decide).

Like rate_limit.py, this is best-effort abuse control for an unprotected
deployment, not distributed rate limiting: the buckets are per process, and
requests whose identity falls back to the shared bucket (see
SharedFallbackResolver) can collectively exhaust one another's limit.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable

from fastapi import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.core.rate_limit import (
    DirectPeerResolver,
    FixedWindowLimiter,
    ForwardedForResolver,
    SharedFallbackResolver,
    ThrottleResult,
)

logger = logging.getLogger("kisanmitra.request_guard")

# Streamed-body cap per GUARDED request, decided against actual received
# bytes (never against a declared length).
MAX_REQUEST_BYTES = 16 * 1024
# Content-Length pre-check applied to GUARDED paths only: a cheap early
# reject of impossible declarations before the gate reads anything. The
# streamed count above stays the authority; the header never accepts, and
# unguarded paths (webhook) are untouched by either check.
MAX_CONTENT_LENGTH_BYTES = 16 * 1024
ADVISORY_LIMIT_PER_MINUTE = 30     # /api/v1/farmer/advisory
CONVERSATION_LIMIT_PER_MINUTE = 60  # /api/v1/conversation/message
MAX_ADVISORY_QUERY_CHARS = 1000    # semantic cap, counted in characters
MAX_MESSAGE_TEXT_CHARS = 2000

# path -> per-minute limit. Exact paths only (and their trailing-slash form);
# the webhook and every other route keep their own auth and are untouched by
# A1 entirely — including the header pre-check, since the WhatsApp webhook
# legitimately receives Meta-signed payloads of any sane size and has its own
# verification (a global byte cap could silently break a delivery).
GUARDED_PATHS: dict[str, int] = {
    "/api/v1/farmer/advisory": ADVISORY_LIMIT_PER_MINUTE,
    "/api/v1/conversation/message": CONVERSATION_LIMIT_PER_MINUTE,
}


class RequestGuardMiddleware:
    """Content-Length pre-check on every path; guarded paths additionally get
    the streamed-byte cap and the fixed-window throttle, decided in that order.

    Plain ASGI rather than BaseHTTPMiddleware: the gate must own the receive
    channel to count real body bytes, and the webhook's raw-body HMAC
    verification downstream must keep seeing an untouched stream (it is not a
    guarded path in A1, and a base-class wrap of the whole app would put every
    route through an extra task group for no benefit).
    """

    def __init__(self, app: ASGIApp, *, trust_proxy_headers: bool = False) -> None:
        self.app = app
        self.limiter = FixedWindowLimiter()
        # Resolution chain, first non-None wins. DirectPeerResolver is the only
        # identity the server controls today. ForwardedForResolver is wired
        # ONLY when an operator explicitly opts into header trust — no
        # deployment has verified that proxy behaviour yet, which is exactly
        # why validate_production_settings rejects it in production.
        self._resolvers = [DirectPeerResolver()]
        if trust_proxy_headers:
            logger.warning("Request guard trusting X-Forwarded-For without a "
                           "verified proxy — bucket keys are caller-controlled; "
                           "this must never be enabled in production.")
            self._resolvers.append(ForwardedForResolver())
        self._fallback = SharedFallbackResolver()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = self._limit_for(scope.get("path", ""))
        if limit is None:
            # Unguarded paths (webhook included: Meta-signed payloads have
            # their own verification and may legitimately exceed 16 KB) are
            # fully untouched by A1.
            await self.app(scope, receive, send)
            return

        # Cheap header pre-check on guarded paths (a cheap early reject
        # before reading anything); the streamed count below stays the
        # authority.
        rejected = self._content_length_reject(scope)
        if rejected is not None:
            await rejected(scope, receive, send)
            return

        if scope.get("method", "").upper() not in ("POST", "PUT", "PATCH"):
            await self.app(scope, receive, send)
            return

        # Pre-read the body in full (bounded by MAX_REQUEST_BYTES) BEFORE any
        # bucket is consumed, so a malformed, throttled or oversized request
        # can never occupy downstream resources or count against a limit it
        # never reached.
        read = await self._read_body(receive)

        if read["disconnected"]:
            # The client vanished mid-body; there is nobody left to answer.
            return

        if read["oversized"]:
            # Bytes beyond the cap were counted and dropped, never parsed. The
            # remainder of a truncated-at-cap stream is left to the server,
            # which terminates the connection once the request completes.
            logger.info("Rejected oversized request body (%d+ streamed bytes) on %s peer=%r",
                        MAX_REQUEST_BYTES, scope.get("path"), scope.get("client"))
            await JSONResponse({"detail": "Request body too large.",
                                "max_bytes": MAX_REQUEST_BYTES},
                               status_code=413)(scope, receive, send)
            return

        throttle = self.limiter.consume(self._bucket_key(scope), limit)
        if not throttle.allowed:
            logger.info("Throttled guarded request on %s (retry-after=%ds)",
                        scope.get("path"), throttle.retry_after_seconds)
            # The bounded body is already fully consumed above, so the worker
            # is never stuck reading a rejected request.
            await self._throttled_response(throttle)(scope, receive, send)
            return

        # Hand downstream a replay of the exact bytes we admitted; after the
        # replayed body, pass the raw stream tail (http.disconnect) through.
        body_message = read["message"]
        played = False

        async def guarded_receive() -> Message:
            nonlocal played
            if not played:
                played = True
                return body_message
            return await receive()

        await self.app(scope, guarded_receive, send)

    @staticmethod
    async def _read_body(receive: Receive) -> dict:
        """Stream the body, counting REAL bytes; stop at the cap.

        Returns {"message": the accumulated single-shot body message,
        "oversized": bool, "disconnected": bool}. Never holds more than
        MAX_REQUEST_BYTES + one chunk of memory, and never trusts
        Content-Length — a lying or absent length header is irrelevant
        because the decision uses only bytes actually received.
        """
        body = bytearray()
        oversized = False
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return {"message": None, "oversized": False, "disconnected": True}
            if message["type"] != "http.request":
                continue
            body.extend(message.get("body", b""))
            if len(body) > MAX_REQUEST_BYTES:
                oversized = True
                break
            if not message.get("more_body", False):
                break
        return {"message": {"type": "http.request", "body": bytes(body),
                            "more_body": False},
                "oversized": oversized, "disconnected": False}

    @staticmethod
    def _content_length_reject(scope: Scope) -> JSONResponse | None:
        """Reject a lying/impossible declared length before reading anything.

        Never ACCEPTS on header strength: a claim within the cap still has to
        survive the streamed-byte count. Only the extremes (negative,
        non-numeric, over cap) are decided here.
        """
        claimed = None
        for name, value in scope.get("headers") or ():
            if name == b"content-length":
                claimed = value.decode("latin-1").strip()
                break
        if claimed is None:
            return None
        try:
            length = int(claimed)
        except ValueError:
            return JSONResponse({"detail": "Invalid Content-Length header."},
                                status_code=400)
        if length < 0:
            return JSONResponse({"detail": "Invalid Content-Length header."},
                                status_code=400)
        if length > MAX_CONTENT_LENGTH_BYTES:
            return JSONResponse({"detail": "Request body too large.",
                                 "max_bytes": MAX_CONTENT_LENGTH_BYTES},
                                status_code=413)
        return None

    def _limit_for(self, path: str) -> int | None:
        return GUARDED_PATHS.get((path or "").rstrip("/"))

    def _bucket_key(self, scope: Scope) -> str:
        for resolver in self._resolvers:
            key = resolver.resolve(scope)
            if key:
                return key
        return self._fallback.resolve(scope) or "shared"

    def _throttled_response(self, throttle: ThrottleResult) -> JSONResponse:
        return JSONResponse(
            {"detail": "Too many requests.", "retry_after": throttle.retry_after_seconds},
            status_code=429,
            headers={"Retry-After": str(throttle.retry_after_seconds)},
        )


def install_request_guard(app, *, trust_proxy_headers: bool = False) -> None:
    """Put the guard outside every user middleware, including CORS.

    Starlette prepends each add_middleware() entry and builds the stack so
    that the LAST-registered user middleware is the OUTERMOST one, so this
    must run AFTER CORSMiddleware has been added (see backend/main.py).
    Two consequences of that placement: a guard rejection never reaches CORS
    processing (browsers will surface 413/429 as an opaque network error —
    the information disclosed by an error page is not worth the leak), and a
    request that passes IS answered with normal CORS headers because it
    flows inward through the CORS middleware untouched.
    """
    app.add_middleware(RequestGuardMiddleware,
                       trust_proxy_headers=trust_proxy_headers)


# ── Semantic input validators (400 layer) ──────────────────
# Called from the handlers after the gate and schema parse, so the ladder is
# 413 → 429 → 422 → 400 → advice. Length is counted in CHARACTERS (what the
# farmer typed), not bytes — the byte cap above already bounds the transport.

def require_non_empty_text(value, field: str, max_chars: int) -> str:
    """Return the stripped text or raise HTTPException(400) with the reason.

    Non-string JSON values ({"query": 123}) reach us because these endpoints
    take a loose dict body; they are a semantic error (400), not a schema
    error — the schema legitimately allows any dict.
    """
    if not isinstance(value, str):
        raise HTTPException(400, detail=f"{field} must be a string.")
    text = value.strip()
    if not text:
        raise HTTPException(400, detail=f"{field} must not be empty.")
    if len(text) > max_chars:
        raise HTTPException(
            400,
            detail=f"{field} is too long: {len(text)} characters (maximum {max_chars}).",
        )
    return text


def require_advisory_query(req: dict) -> str:
    return require_non_empty_text(req.get("query"), "query", MAX_ADVISORY_QUERY_CHARS)


def require_message_text(body, max_chars: int = MAX_MESSAGE_TEXT_CHARS) -> None:
    """Validate the conversation text field: required, non-empty, bounded.

    Button flows may legitimately send text:"" alongside pre-resolved
    entities, so this enforces presence only when nothing else identifies the
    request; the agronomy branch additionally requires real text because it
    retrieves on the raw message.
    """
    if body.text is not None:
        require_non_empty_text(body.text, "text", max_chars)


def require_message_intent(body) -> None:
    """Explicit intent overrides must name a real Intent (or the one bot alias).

    A bogus name silently fell back to NLP parsing, which turns a caller bug
    into a confidently wrong answer instead of a clean 400.
    """
    if body.intent is None:
        return
    from backend.services.message_handler import Intent

    if body.intent == "CONFIRM_DECLARE_CROP":
        return
    if body.intent not in Intent.__members__:
        raise HTTPException(400, detail=f"Unknown intent {body.intent!r}.")


def bounded_sender_id(value: str, max_length: int, field: str = "sender_id") -> str:
    """Reject ids that cannot fit the String(20) identity column.

    ChatHistory.phone_number is VARCHAR(20) NOT NULL; a longer id used to blow
    up at commit time (and now would surface via the best-effort logging path,
    silently losing telemetry). A 400 at the edge names the problem instead.
    """
    if len(value or "") > max_length:
        raise HTTPException(
            400, detail=f"{field} is too long: {len(value)} characters (maximum {max_length})."
        )
    return value


def guarded_paths() -> Iterable[str]:
    return tuple(GUARDED_PATHS)
