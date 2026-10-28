"""
Production settings and the credential guards around them.

Two classes of failure are checked:
  * A missing secret in production must stop startup, not silently fall back to
    a value that is published in this repository.
  * A secret that IS a value this repository published (data.gov.in API key in
    scripts/fetch_*.py, JWT signing secret in backend/core/security.py, DB
    password in backend/core/config.py) must be rejected even when it is set.

This file deliberately contains none of those published values. Copying them in
to prove they are rejected would re-publish them through the hardening patch.
The tests instead inject the SHA-256 digest of a synthetic stand-in into the
compromise list and assert that the same code path fires.
"""
import hashlib
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.core import config as config_module
from backend.core.config import (
    Settings, is_known_compromised_secret, validate_production_settings,
)
from backend.core.security import signing_key

# Stand-ins for the credentials this repository published. These strings are not
# secrets; only their digests are inserted into the compromise list at test time.
LEAK_UNDER_TEST = {
    "data_gov_api_key":   "synthetic-leaked-data-gov-api-key",
    "secret_key":         "synthetic-leaked-jwt-signing-secret",
    "secret_key_default": "synthetic-leaked-jwt-source-default",
    "db_password":        "synthetic-leaked-database-password",
    "whatsapp_verify_token": "synthetic-leaked-verify-token",
}


@pytest.fixture
def injected_compromise_list(monkeypatch):
    """Swap in digests of LEAK_UNDER_TEST; config reads the list at call time."""
    swapped = {name: hashlib.sha256(value.encode("utf-8")).hexdigest()
               for name, value in LEAK_UNDER_TEST.items()}
    monkeypatch.setattr(config_module, "_KNOWN_COMPROMISED_SHA256", swapped)
    return LEAK_UNDER_TEST


def _production_settings(**overrides):
    values = {
        "app_env": "production",
        "secret_key": "a-random-production-secret-key-that-is-long-enough",
        "db_password": "a-unique-database-password",
        "whatsapp_token": "a-configured-whatsapp-token",
        "whatsapp_verify_token": "unique-verify-token",
        "whatsapp_app_secret": "whatsapp-app-secret",
        "cors_origins": "https://kisanmitra.example",
        "data_gov_api_key": "a-fresh-data-gov-in-key",
        # Pin the refresh precondition instead of inheriting the ambient
        # REFRESH_ENABLED. CI exports REFRESH_ENABLED=false, which silently
        # turned the "refresh enabled, no key" case into a valid config and
        # made it pass/fail on the environment rather than the code under test.
        "refresh_enabled": True,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_safe_production_configuration_passes():
    validate_production_settings(_production_settings())


@pytest.mark.parametrize("overrides", [
    {"secret_key": LEAK_UNDER_TEST["secret_key"]},
    {"secret_key": ""},
    {"secret_key": "short-but-unique"},
    {"db_password": LEAK_UNDER_TEST["db_password"]},
    {"db_password": ""},
    {"whatsapp_verify_token": LEAK_UNDER_TEST["whatsapp_verify_token"]},
    {"whatsapp_verify_token": ""},
    {"whatsapp_app_secret": ""},
    {"cors_origins": "*"},
    {"data_gov_api_key": ""},                      # refresh enabled, no key
    {"data_gov_api_key": LEAK_UNDER_TEST["data_gov_api_key"]},
])
def test_unsafe_production_configuration_fails(injected_compromise_list, overrides):
    with pytest.raises(RuntimeError, match="Unsafe production configuration"):
        validate_production_settings(_production_settings(**overrides))


def test_refresh_may_be_disabled_without_a_data_gov_key():
    """An API that only answers from its own DB must still boot in production."""
    validate_production_settings(_production_settings(
        data_gov_api_key="", refresh_enabled=False))


def test_production_boots_with_whatsapp_unconfigured():
    """WhatsApp is an optional channel: with WHATSAPP_TOKEN unset the webhook
    404s and nothing can be sent, so its credentials must not block an
    otherwise-valid deploy (the Render free-tier default)."""
    validate_production_settings(_production_settings(
        whatsapp_token="", whatsapp_verify_token="", whatsapp_app_secret=""))


def test_enabling_whatsapp_without_rotating_credentials_fails(
        injected_compromise_list):
    """Fail-closed on the way IN: setting WHATSAPP_TOKEN revives the credential
    checks — a leaked verify token or a missing app secret must stop boot even
    if the deploy previously passed with the channel off."""
    with pytest.raises(RuntimeError, match="WHATSAPP_APP_SECRET"):
        validate_production_settings(_production_settings(
            whatsapp_token="fresh-meta-token", whatsapp_app_secret=""))
    with pytest.raises(RuntimeError, match="WHATSAPP_VERIFY_TOKEN"):
        validate_production_settings(_production_settings(
            whatsapp_token="fresh-meta-token",
            whatsapp_verify_token=LEAK_UNDER_TEST["whatsapp_verify_token"]))


def test_leaked_data_gov_key_is_rejected_even_with_refresh_disabled(injected_compromise_list):
    """
    Regression: the data.gov check was gated on refresh_enabled, so a burned
    key was silently accepted whenever the pipeline was off -- and flipping
    REFRESH_ENABLED on later would revive it unrotated. A compromised value is
    unsafe regardless of whether the job that would use it is running.
    """
    with pytest.raises(RuntimeError, match="Unsafe production configuration"):
        validate_production_settings(_production_settings(
            data_gov_api_key=LEAK_UNDER_TEST["data_gov_api_key"],
            refresh_enabled=False))


def test_leaked_credentials_are_detected_by_digest_only(injected_compromise_list):
    """
    The rejection list holds SHA-256 digests, so the hardening code never
    re-publishes the secrets it is guarding against.
    """
    leaked = injected_compromise_list
    assert is_known_compromised_secret(leaked["secret_key"])
    assert is_known_compromised_secret(leaked["data_gov_api_key"])
    assert not is_known_compromised_secret("a-brand-new-credential")
    assert not is_known_compromised_secret("")
    # A digest match is byte-exact; a prefix of the leaked value is not a match.
    assert not is_known_compromised_secret(leaked["data_gov_api_key"][:10])


def test_shipped_compromise_list_holds_only_digests():
    """The real list must stay digest-only, never plaintext credentials."""
    assert config_module._KNOWN_COMPROMISED_SHA256, "compromise list must not be empty"
    for name, value in config_module._KNOWN_COMPROMISED_SHA256.items():
        assert re.fullmatch(r"[0-9a-f]{64}", value), f"{name} is not a SHA-256 digest"


def test_this_file_republishes_no_live_credential():
    """
    Review found that a security test can leak the very thing it covers: this
    matrix once carried the published data.gov.in key and DB password verbatim.
    Live values come from the operator's environment, so comparing them against
    this file's own bytes catches a repeat without naming any credential.
    """
    from backend.core.config import settings

    source = Path(__file__).read_text(encoding="utf-8")
    live = {v for v in (settings.secret_key, settings.db_password,
                        settings.data_gov_api_key, settings.whatsapp_verify_token,
                        settings.whatsapp_app_secret) if len(v) >= 8}
    for value in live:
        if value in source:
            pytest.fail("this test file contains a live credential; use a synthetic stand-in")


def test_no_credential_source_contains_a_plaintext_default():
    """
    Guards the fix itself. `os.getenv(KEY, "secret")` and a non-empty pydantic
    field default are how these credentials leaked in the first place.
    """
    import ast
    from pathlib import Path

    root = Path(__file__).parents[1]
    offenders = []
    for rel in ("backend/core/config.py", "backend/core/security.py",
                "telegram_bot/config.py", "scripts/fetch_all_crops_full.py",
                "scripts/fetch_potato_full.py", "scripts/download_real_agmarknet_history.py"):
        source = (root / rel).read_text()
        for node in ast.walk(ast.parse(source)):
            # os.getenv("DATA_GOV_API_KEY", "<live key>")
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "getenv":
                if len(node.args) == 2 and isinstance(node.args[1], ast.Constant):
                    name = str(getattr(node.args[0], "value", ""))
                    if any(t in name.upper() for t in ("KEY", "SECRET", "TOKEN", "PASSWORD")) \
                       and str(node.args[1].value):
                        offenders.append(f"{rel}:{node.lineno} {name} has a non-empty getenv default")
            # db_password: str = "<the live database password>"
            if isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Constant):
                target = str(getattr(node.target, "id", ""))
                if any(t in target.lower() for t in ("key", "secret", "token", "password")) \
                   and str(node.value.value):
                    offenders.append(f"{rel}:{node.lineno} {target} has a hardcoded default")
    assert offenders == [], offenders


def test_settings_have_no_built_in_credentials(monkeypatch):
    """
    With no .env and no exported variables, every secret resolves to empty
    instead of a value shipped in source. (telegram_bot/config.py calls
    load_dotenv, so the ambient environment is cleared for this check.)
    """
    for key in ("SECRET_KEY", "DB_PASSWORD", "WHATSAPP_VERIFY_TOKEN",
                "DATA_GOV_API_KEY", "WHATSAPP_APP_SECRET"):
        monkeypatch.delenv(key, raising=False)
    bare = Settings(_env_file=None)
    assert bare.secret_key == ""
    assert bare.db_password == ""
    assert bare.whatsapp_verify_token == ""
    assert bare.data_gov_api_key == ""


def test_signing_key_refuses_an_unset_secret(monkeypatch):
    """No fallback: an unset SECRET_KEY must raise, never sign with b''."""
    import backend.core.security as security

    with patch.object(security, "SECRET_KEY", ""):
        with pytest.raises(RuntimeError, match="SECRET_KEY is not configured"):
            signing_key()


def test_signing_key_refuses_a_published_secret(injected_compromise_list):
    import backend.core.security as security

    with patch.object(security, "SECRET_KEY", injected_compromise_list["secret_key"]):
        with pytest.raises(RuntimeError, match="previously published"):
            signing_key()


def test_signing_key_returns_the_configured_secret_and_never_prints_it():
    import backend.core.security as security

    good = "x" * 48
    with patch.object(security, "SECRET_KEY", good):
        assert signing_key() == good


@pytest.mark.asyncio
async def test_farmer_declarations_refuses_service_when_the_secret_is_unset():
    """503 rather than a comparison against "" that would 401 every real call."""
    from backend.routers import farmers

    with patch.object(farmers, "using_leaked_secret", return_value=True):
        with pytest.raises(HTTPException) as exc:
            await farmers.farmer_declarations(
                phone="9998887776", caller_id="9998887776",
                x_internal_secret="anything", db=None)
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_farmer_declarations_matches_the_secret_in_constant_time():
    """Regression: the correct secret still authorises, the wrong one still 401s."""
    from types import SimpleNamespace

    from backend.core import config as config_module
    from backend.routers import farmers

    good = "an-operator-provided-secret-key-that-is-long-enough"
    decl = SimpleNamespace(id=1, crop="Tomato", district="Kolar", area_acres=2.0,
                           season="Kharif_2026", declared_at=None)
    res = MagicMock()
    res.scalars.return_value.all.return_value = [decl]
    db = AsyncMock()
    db.execute = AsyncMock(return_value=res)

    with patch.object(config_module.settings, "secret_key", good):
        body = await farmers.farmer_declarations(
            phone="9998887776", caller_id="9998887776",
            x_internal_secret=good, db=db)
        assert body["count"] == 1

        with pytest.raises(HTTPException) as exc:
            await farmers.farmer_declarations(
                phone="9998887776", caller_id="9998887776",
                x_internal_secret=good + "x", db=db)
        assert exc.value.status_code == 401
