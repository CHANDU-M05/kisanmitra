"""
Stage E — CORS fail-closed security fix.

The previous configuration resolved an unset CORS_ORIGINS to the wildcard "*"
while also sending allow_credentials=True — the one combination browsers refuse
and that lets any site make credentialed cross-origin requests. These tests pin
the corrected contract:

  * development substitutes an explicit loopback allowlist (never "*"),
  * production requires at least one valid HTTPS origin or fails at startup,
  * every other environment denies all cross-origin requests when unconfigured,
  * the middleware never pairs a wildcard origin with credentials,
  * an origin that was not configured is not granted access.

No credentials or production systems are touched: the settings objects are built
in-process with _env_file=None and synthetic values.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from backend.core.config import (
    DEV_DEFAULT_CORS_ORIGINS,
    Settings,
    is_valid_https_origin,
    parse_cors_origins,
    resolve_cors_origins,
    validate_production_settings,
)


def _production_settings(cors_origins: str) -> Settings:
    """A production config whose only variable under test is CORS_ORIGINS.

    Every other env-dependent field is pinned here, not left to defaults: a
    baseSettings instance still reads os.environ, and earlier tests in the suite
    export WHATSAPP_TOKEN, which would otherwise flip the (unrelated) WhatsApp
    checks to "configured" and fail these tests only during a full run. Pinning
    keeps the assertion scoped to the CORS rule under test.
    """
    return Settings(
        _env_file=None,
        app_env="production",
        secret_key="a-random-production-secret-key-that-is-long-enough",
        db_password="a-unique-database-password",
        data_gov_api_key="",
        refresh_enabled=False,
        # WhatsApp left explicitly unconfigured so its optional-channel checks
        # stay skipped regardless of ambient environment variables.
        whatsapp_token="",
        whatsapp_verify_token="",
        whatsapp_app_secret="",
        cors_origins=cors_origins,
    )


def _app_with_origins(origins: list[str]) -> FastAPI:
    """Mirror backend/main.py's wiring: resolved origins + credentials, no '*'.

    Building the app from resolve_cors_origins output (rather than importing the
    module-level app) keeps the assertion on the real middleware contract while
    staying independent of the ambient environment.
    """
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/ping")
    def ping():
        return {"ok": True}

    return app


# 1. Development default is exactly the two approved loopback origins. ────────
def test_development_default_is_the_explicit_loopback_allowlist():
    resolved = resolve_cors_origins("development", "")
    assert resolved == ["http://localhost:3000", "http://127.0.0.1:3000"]
    assert resolved == list(DEV_DEFAULT_CORS_ORIGINS)
    assert "*" not in resolved


def test_development_drops_a_configured_wildcard_rather_than_trusting_it():
    # Even if an operator types CORS_ORIGINS=* in dev, "*" is never honoured.
    assert resolve_cors_origins("development", "*") == list(DEV_DEFAULT_CORS_ORIGINS)
    assert resolve_cors_origins("development", "*,https://x.example") == ["https://x.example"]


# 2-7. Production validation is fail-closed. ──────────────────────────────────
@pytest.mark.parametrize("cors", [
    pytest.param("",           id="empty"),
    pytest.param("   ",        id="whitespace-only"),
    pytest.param("*",          id="wildcard"),
    pytest.param("http://insecure.example", id="insecure-http"),
    pytest.param("https://host/has-a-path", id="malformed-path-origin"),
    pytest.param("not a url",  id="not-a-url"),
])
def test_production_rejects_invalid_cors_configuration(cors):
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        validate_production_settings(_production_settings(cors))


def test_production_accepts_a_valid_https_origin():
    # The real deploy shapes: the Cloudflare Pages origin and the .example cert.
    for good in ("https://your-project.pages.dev", "https://kisanmitra.example.com"):
        validate_production_settings(_production_settings(good))
        assert resolve_cors_origins("production", good) == [good]


def test_production_accepts_multiple_https_origins_but_rejects_one_bad():
    validate_production_settings(
        _production_settings("https://a.example,https://b.example"))
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        validate_production_settings(
            _production_settings("https://a.example,http://b.example"))


# is_valid_https_origin unit behaviour. ───────────────────────────────────────
@pytest.mark.parametrize("origin,ok", [
    ("https://kisanmitra.example", True),
    ("https://host.example:8443", True),
    ("https://host.example/", True),          # single trailing slash tolerated
    ("http://host.example", False),           # insecure
    ("https://user:pw@host.example", False),  # embedded credentials
    ("https:///no-host", False),
    ("*", False),
    ("", False),
])
def test_is_valid_https_origin(origin, ok):
    assert is_valid_https_origin(origin) is ok


def test_parse_cors_origins_trims_and_drops_blanks():
    assert parse_cors_origins(" https://a.example , ,https://b.example, ") == \
        ["https://a.example", "https://b.example"]
    assert parse_cors_origins(None) == []


# 8. A non-development environment must be explicitly configured. ─────────────
def test_other_environments_are_not_substituted_with_development_origins():
    # "staging"/"test" left unset deny everything instead of inheriting the
    # loopback allowlist or falling back to "*".
    assert resolve_cors_origins("staging", "") == []
    assert resolve_cors_origins("test", "") == []
    assert resolve_cors_origins("staging", "*") == []


def test_parse_and_resolve_share_one_definition_for_production():
    # Whatever validate accepted, resolve hands the middleware the same list —
    # no divergence between the startup check and runtime behaviour.
    raw = "https://a.example,https://b.example"
    validate_production_settings(_production_settings(raw))
    assert resolve_cors_origins("production", raw) == parse_cors_origins(raw)


# 9. Middleware never emits a wildcard origin together with credentials. ───────
def test_middleware_never_returns_wildcard_with_credentials():
    # Simulate the historical bad default: an unset config in dev resolves to
    # explicit origins, never "*", so the credentialed response names an origin.
    app = TestClient(_app_with_origins(resolve_cors_origins("development", "")))
    res = app.get("/ping", headers={"Origin": "http://localhost:3000"})
    assert res.headers.get("access-control-allow-origin") != "*"
    assert res.headers.get("access-control-allow-credentials") == "true"


# 10. A configured origin receives the expected CORS response. ────────────────
def test_configured_origin_is_granted_access():
    origin = "https://your-project.pages.dev"
    app = TestClient(_app_with_origins(resolve_cors_origins("production", origin)))
    res = app.get("/ping", headers={"Origin": origin})
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == origin


# 11. An origin that was not configured is not granted access. ────────────────
def test_unconfigured_origin_is_not_granted_access():
    allowed = "https://your-project.pages.dev"
    app = TestClient(_app_with_origins(resolve_cors_origins("production", allowed)))
    res = app.get("/ping", headers={"Origin": "https://evil.example"})
    assert res.status_code == 200  # request still served
    # No CORS grant is emitted for an untrusted origin, and never a wildcard.
    assert res.headers.get("access-control-allow-origin") is None


def test_empty_allowlist_denies_all_cross_origins():
    # A non-dev environment left unset resolves to [] → no origin is granted.
    app = TestClient(_app_with_origins(resolve_cors_origins("staging", "")))
    res = app.get("/ping", headers={"Origin": "https://anywhere.example"})
    assert res.headers.get("access-control-allow-origin") is None
