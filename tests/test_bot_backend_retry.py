"""
tests/test_bot_backend_retry.py — the bot must survive a Render free cold start.

send_to_engine's first timeout usually means the backend was asleep, and the
attempt itself woke it: one retry after a short pause lands on an instance that
is already up. These tests pin exactly that contract (and its limits):

  * timeout once → sleep 3 s → retry → real result (farmer never sees the
    fallback for a merely-slow first answer),
  * timeout twice → friendly fallback, and NO third attempt,
  * HTTP 5xx → fallback immediately: retry is for timeouts only, because a
    server that answered 500 is awake and re-posting can duplicate work.

No network is touched: httpx.AsyncClient is stubbed per test.
"""
import os

# telegram_bot.config validates its env vars at IMPORT time (_require raises
# OSError). Locally a .env satisfies them; CI's clean checkout has none, so
# these tests would crash pytest at collection (exit 2). Pin inert values
# BEFORE importing the module under test; setdefault keeps any real
# environment untouched.
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-bot-token")
os.environ.setdefault("SECRET_KEY", "test-secret-key-0123456789abcdef")

import httpx  # noqa: E402
import pytest  # noqa: E402

from telegram_bot import backend_client  # noqa: E402


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _stub_client(outcomes, calls):
    """AsyncClient stand-in: each post() pops the next outcome (raise it if
    it is an exception, return it otherwise) and records the call."""
    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None):
            calls.append((url, json))
            outcome = outcomes[min(len(calls), len(outcomes)) - 1]
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

    return _Client


@pytest.fixture
def no_pause(monkeypatch):
    """Swap asyncio.sleep for a recorder so the retry costs no wall clock."""
    slept = []

    async def _sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(backend_client.asyncio, "sleep", _sleep)
    return slept


@pytest.mark.asyncio
async def test_a_timeout_is_retried_once_and_the_retry_wins(monkeypatch, no_pause):
    calls = []
    good = _Resp({"type": "price", "answer": "₹45"})
    monkeypatch.setattr(backend_client.httpx, "AsyncClient", _stub_client(
        [httpx.TimeoutException("cold start"), good], calls))

    result = await backend_client.send_to_engine("999", "tomato price")

    assert result == {"type": "price", "answer": "₹45"}
    assert len(calls) == 2, "exactly one retry"
    assert no_pause == [3], "one 3-second pause between attempts"


@pytest.mark.asyncio
async def test_a_second_timeout_falls_back_without_further_retries(monkeypatch, no_pause):
    calls = []
    monkeypatch.setattr(backend_client.httpx, "AsyncClient", _stub_client(
        [httpx.TimeoutException("still asleep")], calls))

    result = await backend_client.send_to_engine("999", "tomato price")

    assert result == backend_client._FALLBACK_RESULT
    assert len(calls) == 2, "the retry limit is one, not unbounded"
    assert no_pause == [3]


@pytest.mark.asyncio
async def test_http_5xx_is_not_retried(monkeypatch, no_pause):
    calls = []
    req = httpx.Request("POST", "http://backend.test/api/v1/conversation/message")
    err = httpx.HTTPStatusError("boom", request=req, response=httpx.Response(500, request=req))
    monkeypatch.setattr(backend_client.httpx, "AsyncClient", _stub_client([err], calls))

    result = await backend_client.send_to_engine("999", "tomato price")

    assert result == backend_client._FALLBACK_RESULT
    assert len(calls) == 1, "an answered 5xx must not be reposted"
    assert no_pause == []
