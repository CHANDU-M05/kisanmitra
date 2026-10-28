"""
tests/test_secret_redaction.py — P0: a credential must not become log text.

Discovered during the October live verification, not by reading code: when the
data.gov.in request fails, `requests` renders the whole URL into the exception
string, and the API key IS a URL parameter. That string was then

  * logged by kisanmitra.data_refresh,
  * written to data_refresh_runs.error and .details,
  * returned by /internal/data/status and by scripts/refresh_prices.py.

One live upstream timeout was therefore enough to put the working key into
logs/kisanmitra.log and into the database. These tests pin the redaction that
now runs on the way in, on the way out, and on every rendered log line.
"""
from __future__ import annotations

import datetime
import logging
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import requests

from backend.core.config import redact_secrets, settings
from backend.services import data_refresh

FAKE_KEY = "fakedgovkey0123456789abcdef0011223344556677"
URL_WITH_KEY = f"https://api.data.gov.in/resource/3598?api-key={FAKE_KEY}&format=json&limit=1000"


@pytest.fixture
def fake_key(monkeypatch):
    """A known key in place of the real one, so a leak is detectable and portable."""
    monkeypatch.setattr(settings, "data_gov_api_key", FAKE_KEY)
    return FAKE_KEY


# ── the primitive ──────────────────────────────────────────

def test_url_parameter_credential_is_redacted(fake_key):
    clean = redact_secrets(URL_WITH_KEY)
    assert fake_key not in clean
    assert "api-key=[REDACTED]" in clean
    # Everything that is not a credential survives: this is a scrub, not a mute.
    assert "format=json" in clean


def test_bare_secret_value_is_redacted_even_without_a_parameter_name(fake_key):
    assert fake_key not in redact_secrets(f"retrying after rejecting {fake_key} as invalid")


def test_ordinary_content_is_not_mangled():
    # Over-eager redaction would be its own bug: prices and dates must pass through.
    sentence = "Tomato 3595.0 /quintal at Kolar on 2026-08-25 (53 days old)"
    assert redact_secrets(sentence) == sentence


def test_empty_and_none_pass_through():
    assert redact_secrets(None) is None
    assert redact_secrets("") == ""


# ── on the way in: the fetcher ─────────────────────────────

def test_network_failure_carries_no_key(fake_key):
    def boom(*args, **kwargs):
        raise requests.ConnectTimeout(
            f"HTTPSConnectionPool(host='api.data.gov.in', port=443): "
            f"Max retries exceeded with url: /resource/3598?api-key={fake_key}&format=json"
        )

    with patch("requests.Session.get", side_effect=boom):
        with pytest.raises(data_refresh.RefreshFetchError) as excinfo:
            data_refresh.fetch_window(
                "Tomato",
                datetime.date(2026, 10, 1),
                datetime.date(2026, 10, 15),
                api_key=fake_key, limit=100, max_pages=1,
                retry_backoff=0.0, pace_seconds=0.0,
            )

    message = str(excinfo.value)
    assert fake_key not in message
    assert "[REDACTED]" in message
    # The operator still needs to know what actually went wrong.
    assert "Max retries exceeded" in message


def test_http_error_body_is_scrubbed_before_it_becomes_the_failure_reason(fake_key):
    response = MagicMock(status_code=502, text=f"Bad Gateway: rejected api-key={fake_key}")
    with patch("requests.Session.get", return_value=response):
        with pytest.raises(data_refresh.RefreshFetchError) as excinfo:
            data_refresh.fetch_window(
                "Tomato",
                datetime.date(2026, 10, 1),
                datetime.date(2026, 10, 15),
                api_key=fake_key, limit=100, max_pages=1,
                retry_backoff=0.0, pace_seconds=0.0,
            )
    assert fake_key not in str(excinfo.value)


# ── on the way in: what gets stored ────────────────────────

def _res(scalar=None, scalar_one=None):
    out = MagicMock()
    out.scalar.return_value = scalar
    out.scalar_one_or_none.return_value = scalar_one
    return out


@pytest.mark.asyncio
async def test_a_failed_run_is_stored_without_the_key(fake_key):
    """
    The pipeline must still record THAT and WHY it failed. Redaction may not turn
    a `failed` run into a silent one.
    """
    def exploding_fetcher(crop, window_start, window_end):
        raise data_refresh.RefreshFetchError(f"network error fetching {crop}: {URL_WITH_KEY}")

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[_res(scalar_one=None), _res(scalar=None)])
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.rollback = AsyncMock()

    summary = await data_refresh.run_refresh(
        db, trigger="test", fetcher=exploding_fetcher, crops=["Tomato"],
        api_key=fake_key, today=datetime.date(2026, 10, 15),
    )

    assert summary["status"] == "failed"          # honest failure, not swallowed
    assert fake_key not in summary["error"]
    assert "[REDACTED]" in summary["error"]

    run_row = db.add.call_args[0][0]
    assert run_row.status == "failed"
    assert fake_key not in run_row.error
    assert fake_key not in str(run_row.details)   # the JSONB blob is scrubbed too


@pytest.mark.asyncio
async def test_health_read_scrubs_rows_written_before_the_fix(fake_key):
    """Legacy rows hold the raw URL; serving them must not re-leak it."""
    legacy = MagicMock()
    legacy.id, legacy.status, legacy.trigger = 58, "failed", "audit"
    legacy.started_at = legacy.finished_at = None
    legacy.rows_inserted, legacy.rows_rejected = 0, 0
    legacy.error = f"network error fetching Tomato: {URL_WITH_KEY}"

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[
        _res(scalar_one=datetime.datetime(2026, 8, 25)),   # newest market date
        _res(scalar_one=legacy),                           # last refresh run
        _res(scalar=25000),                                # row count
    ])

    health = await data_refresh.data_freshness(db, today=datetime.date(2026, 10, 15))

    assert fake_key not in health["last_refresh"]["error"]
    assert "[REDACTED]" in health["last_refresh"]["error"]
    assert health["last_refresh"]["status"] == "failed"


# ── on the way out: every rendered log line ────────────────

def test_formatter_redacts_the_traceback_not_just_the_message(fake_key):
    from backend.core.logging_config import RedactingFormatter

    record = logging.LogRecord(
        name="kisanmitra.data_refresh", level=logging.ERROR,
        pathname="data_refresh.py", lineno=1, msg="AGMARKNET refresh aborted",
        args=None, exc_info=None,
    )
    try:
        raise ValueError(f"upstream refused {URL_WITH_KEY}")
    except ValueError:
        record.exc_info = sys.exc_info()

    rendered = RedactingFormatter("%(levelname)s - %(message)s").format(record)

    assert fake_key not in rendered
    # The exception text sits below the message; a message filter would miss it.
    assert "ValueError:" in rendered
    assert "[REDACTED]" in rendered


# ── at-rest remediation tool ───────────────────────────────
# A production log and its refresh rows can already hold the key by the time the
# code is fixed, so the scrubber needs the same guarantees: remove the
# credential, keep the diagnosis, and be idempotent on clean text.

def test_scrubber_removes_the_secret_and_keeps_the_diagnosis():
    from scripts.tools.scrub_secret_exposure import scrub_text

    raw = f"GET {URL_WITH_KEY} failed after 30s for Tomato"
    clean, hits = scrub_text(raw, (FAKE_KEY,))
    assert FAKE_KEY not in clean
    assert hits >= 1
    assert "failed after 30s for Tomato" in clean
    assert "api-key=[REDACTED]" in clean


def test_scrubber_is_idempotent_on_already_clean_text():
    from scripts.tools.scrub_secret_exposure import scrub_text

    clean_line = "network error: api-key=[REDACTED]&format=json"
    assert scrub_text(clean_line, (FAKE_KEY,)) == (clean_line, 0)
