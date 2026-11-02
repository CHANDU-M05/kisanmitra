"""
backend/core/rate_limit.py — Best-effort abuse control for shared endpoints.

This is deliberately NOT production-grade distributed rate limiting. It is a
small fixed-window counter with two properties the A1 hardening requires:

  1. A bucket key may only come from an identifier the server actually
     controls. The ASGI scope's ``client`` tuple is the peer the TCP connection
     came from; caller-supplied forwarding headers (X-Forwarded-For and
     friends) are NOT verified by any deployment proxy in this stage, so they
     are never trusted — keying on them would let every caller choose its own
     bucket (header spoofing) or collapse all users behind one proxy address
     into a shared bucket (collateral throttling).
  2. When no trustworthy client identifier exists (no peer in the scope, or a
     deployment that has enabled forwarding-header trust without ever
     verifying it upstream), ALL traffic that resolves this way shares one
     fallback bucket per process. That fallback can be exhausted by a single
     caller and will then throttle every other legitimate caller with it.
     This is the honest failure mode: abuse control, not per-user fairness.

Key resolution and limit policy live here and in request_guard.py only, so a
later stage that terminates TLS behind a verified proxy (a trusted
X-Forwarded-For strategy, or PROXY protocol) can replace
DirectPeerResolver/SharedFallbackResolver without touching handlers.
Nothing here keys on sender_id — a caller can open unlimited sender identities
and a shared proxy address must not punish them all differently per identity.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

# The bucket key when the peer address is unavailable (in-process test clients
# and ASGI transports that omit ``scope["client"]``) or when forwarding-header
# trust has been enabled without any upstream verification to back it up.
SHARED_BUCKET_KEY = "shared"

# Fixed window (seconds). A fixed window can admit a short burst of up to
# 2x the limit across a boundary; for an abuse-control ceiling rather than a
# billing meter, the simplicity and the exact Retry-After are worth it.
WINDOW_SECONDS = 60.0


@dataclass(frozen=True)
class ThrottleResult:
    allowed: bool
    retry_after_seconds: int = 0


class BucketKeyResolver(Protocol):
    """Turns an ASGI connection scope into a bucket key, or None to fall back."""

    def resolve(self, scope: dict) -> str | None:  # pragma: no cover - protocol
        ...


class DirectPeerResolver:
    """Key on the TCP peer address reported by the server itself.

    Under direct load this is accurate; note the known caveat that many
    clients behind one NAT appear as one bucket. That is a property of the
    (unverified, proxy-less) deployment topology, not a header an attacker
    controls.
    """

    def resolve(self, scope: dict) -> str | None:
        client = scope.get("client") or ()
        if len(client) >= 2 and client[0]:
            return str(client[0])
        return None


class SharedFallbackResolver:
    """Everything without a trustworthy identity shares one bucket.

    Returns SHARED_BUCKET_KEY so such requests are at least countable, and
    documents (here and in the guard's startup warning) that one aggressive
    caller can exhaust the bucket for all of them.
    """

    def resolve(self, scope: dict) -> str | None:
        return SHARED_BUCKET_KEY


class ForwardedForResolver:
    """Leftmost X-Forwarded-For entry. Gated on settings.trust_proxy_headers.

    SECURITY: trusting this header is only sound when every request genuinely
    passes through a proxy that overwrites it. No deployment stage verified so
    far, production validation refuses to boot with it enabled, and unit tests
    cover the arithmetic in isolation only. Do not wire this into a live app
    until a verified proxy strategy exists (A1 decision, open question #1).
    """

    def resolve(self, scope: dict) -> str | None:
        for name, _value in scope.get("headers") or ():
            if name == b"x-forwarded-for":
                first = _value.decode("latin-1").split(",")[0].strip()
                return first or None
        return None


class FixedWindowLimiter:
    """Per-process fixed-window counter keyed by an opaque bucket string."""

    def __init__(self, window_seconds: float = WINDOW_SECONDS) -> None:
        self._window = window_seconds
        # dict/attribute ops below are atomic under the GIL and every request
        # on one event loop is single-threaded anyway; the worst race is one
        # extra admitted or denied request at a window boundary, which is
        # acceptable for best-effort abuse control.
        self._counts: dict[str, tuple[int, float]] = {}

    def consume(self, key: str, limit: int) -> ThrottleResult:
        """Count one request against `key`; refuse it when the window is full."""
        if limit <= 0:      # defensive: a zero/negative limit must not lock out
            return ThrottleResult(True)
        now = time.monotonic()
        window_start = now - (now % self._window)
        count, start = self._counts.get(key, (0, window_start))
        if start != window_start:
            count = 0
        if count >= limit:
            retry = self._window - (now - window_start)
            return ThrottleResult(False, max(1, min(int(retry + 0.999), int(self._window))))
        self._counts[key] = (count + 1, window_start)
        return ThrottleResult(True)

    def reset(self) -> None:
        """Drop all windows. For tests and process-level restarts only."""
        self._counts.clear()
