"""
tests/test_webhook_verification.py — Meta webhook handshake cannot be satisfied
by an absent token.

The verification endpoint compared `hub.verify_token` with `==` against
settings.whatsapp_verify_token. With WHATSAPP_VERIFY_TOKEN unset (the state of a
fresh clone, and of any deploy that forgot it, because the .env.example default
was itself a published constant) a request carrying an empty token matched and
returned 200 — the handshake looked configured while it enforced nothing.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.core.config import settings
from backend.routers.webhook import router

VERIFY_TOKEN = "unit-test-verify-token-0123456789abcdef"
CHALLENGE = "1158201444"


@pytest.fixture
def client(monkeypatch):
    # The routes 404 unless the channel is configured (WHATSAPP_TOKEN set); the
    # handshake tests below exercise a configured deploy.
    monkeypatch.setattr(settings, "whatsapp_token", SecretStr("unit-test-wa-token"))
    monkeypatch.setattr(settings, "whatsapp_verify_token", VERIFY_TOKEN)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_the_configured_token_echoes_the_challenge(client):
    res = client.get("/webhook/whatsapp", params={
        "hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN,
        "hub.challenge": CHALLENGE,
    })
    assert res.status_code == 200
    assert res.text == CHALLENGE


def test_a_wrong_token_is_refused(client):
    res = client.get("/webhook/whatsapp", params={
        "hub.mode": "subscribe", "hub.verify_token": "not-it",
        "hub.challenge": CHALLENGE,
    })
    assert res.status_code == 403


def test_an_absent_token_does_not_match_a_configured_one(client):
    """The old `==` comparison made an empty token a successful guess."""
    for supplied in ("", None):
        params = {"hub.mode": "subscribe", "hub.challenge": CHALLENGE}
        if supplied is not None:
            params["hub.verify_token"] = supplied
        assert client.get("/webhook/whatsapp", params=params).status_code == 403


def test_an_unconfigured_token_refuses_service_instead_of_matching_blank(monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_token", SecretStr("unit-test-wa-token"))
    monkeypatch.setattr(settings, "whatsapp_verify_token", "")
    app = FastAPI()
    app.include_router(router)
    res = TestClient(app).get("/webhook/whatsapp", params={
        "hub.mode": "subscribe", "hub.verify_token": "", "hub.challenge": CHALLENGE,
    })
    assert res.status_code == 503
    assert "not configured" in res.json()["detail"]
    # 503, not 200: an operator must not be able to believe the webhook is secured.
    assert res.status_code != 200


def test_a_wrong_mode_is_refused_even_with_the_right_token(client):
    res = client.get("/webhook/whatsapp", params={
        "hub.mode": "unsubscribe", "hub.verify_token": VERIFY_TOKEN,
        "hub.challenge": CHALLENGE,
    })
    assert res.status_code == 403


def test_both_routes_404_when_the_channel_is_unconfigured(monkeypatch):
    """WhatsApp is optional in production: an unconfigured WHATSAPP_TOKEN must
    make the routes present as absent, not as live endpoints guarded only by
    credentials a dormant deploy never set."""
    monkeypatch.setattr(settings, "whatsapp_token", SecretStr(""))
    monkeypatch.setattr(settings, "whatsapp_verify_token", VERIFY_TOKEN)
    app = FastAPI()
    app.include_router(router)
    unknown_app = TestClient(app)
    res = unknown_app.get("/webhook/whatsapp", params={
        "hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN,
        "hub.challenge": CHALLENGE,
    })
    assert res.status_code == 404
    res = unknown_app.post("/webhook/whatsapp", json={"entry": []})
    assert res.status_code == 404
