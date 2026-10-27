"""
tests/test_auth_login.py — admin login username normalization & lockout.

Incident 2026-10-27: login_for_access_token lowercased the username for the
brute-force lockout tracker (line 25) but looked the user up in the DB with the
RAW submitted string (line 42). Postgres string comparison is case-sensitive,
so typing "Admin" (the login screen brands everything "ADMIN") never matched
the stored lowercase `admin`, returned 401, and — because the failure counter
is keyed on the lowercased name — could lock the legitimate `admin` account out
for 15 minutes. The fix looks the user up with the SAME normalized value.

These tests drive the handler through a real FastAPI TestClient with the DB and
JWT signing stubbed, so no Neon or secret material is touched.
"""
from __future__ import annotations

import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.core.security as security
from backend.core.database import get_db
from backend.core.models import AdminUser
from backend.core.security import get_password_hash
from backend.routers import auth as auth_module
from backend.routers.auth import router

PASSWORD = "Correct-Horse-Battery-Staple-9"
STORED_USERNAME = "admin"  # seeded lowercase
SIGNING_KEY = "unit-test-signing-key-0123456789abcdef-xyz"  # >=32, not compromised


class _Result:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class _FakeSession:
    """Stands in for AsyncSession: resolves the single AdminUser WHERE lookup."""

    def __init__(self, stored):
        self.stored = stored
        self.lookups: list[str | None] = []

    async def execute(self, stmt):
        looked = None
        for value in stmt.compile().params.values():
            if isinstance(value, str):
                looked = value
        self.lookups.append(looked)
        if self.stored is not None and looked == self.stored.username:
            return _Result(self.stored)
        return _Result(None)


@pytest.fixture
def session():
    stored = AdminUser(username=STORED_USERNAME, hashed_password=get_password_hash(PASSWORD))
    return _FakeSession(stored)


@pytest.fixture
def client(session, monkeypatch):
    auth_module._FAILED_LOGIN_ATTEMPTS.clear()
    monkeypatch.setattr(security, "SECRET_KEY", SIGNING_KEY)
    app = FastAPI()
    app.include_router(router, prefix="/auth")  # mirrors api_router mount
    app.dependency_overrides[get_db] = lambda: session
    yield TestClient(app)
    auth_module._FAILED_LOGIN_ATTEMPTS.clear()


def _login(client, username, password=PASSWORD):
    return client.post("/auth/login", data={"username": username, "password": password})


def test_lowercase_username_succeeds(client):
    res = _login(client, "admin")
    assert res.status_code == 200
    assert res.json()["access_token"]


def test_mixed_case_username_is_normalized_and_succeeds(client, session):
    """The regression: 'Admin' must authenticate, and the DB lookup must use 'admin'."""
    res = _login(client, "Admin")
    assert res.status_code == 200, "case-sensitive lookup rejected a valid admin"
    assert res.json()["access_token"]
    assert session.lookups[-1] == STORED_USERNAME, "handler looked up the raw, not normalized, name"


def test_unknown_case_variant_still_hits_normalized_lookup(client, session):
    res = _login(client, "  ADMIN  ")  # whitespace + case
    assert res.status_code == 200
    assert session.lookups[-1] == STORED_USERNAME


def test_wrong_password_is_401_with_attempts_remaining(client):
    res = _login(client, "admin", password="not-the-password")
    assert res.status_code == 401
    assert "attempt(s) remaining" in res.json()["detail"]


def test_lockout_after_three_failures_returns_429(client):
    codes = [_login(client, "admin", password="bad").status_code for _ in range(3)]
    # 401, 401 then the 3rd crossing MAX_LOGIN_ATTEMPTS triggers the lock.
    assert codes[:2] == [401, 401]
    assert codes[2] == 429


def test_correct_creds_rejected_while_locked_out(client):
    for _ in range(3):
        _login(client, "admin", password="bad")
    # Even the right password is refused during the window — this is the 429
    # the OLD frontend mislabeled as "invalid username or password".
    res = _login(client, "admin")
    assert res.status_code == 429
    assert "locked" in res.json()["detail"].lower()


def test_correct_creds_succeed_after_lockout_expires(client):
    for _ in range(3):
        _login(client, "admin", password="bad")
    assert _login(client, "admin").status_code == 429
    # Simulate the 15-minute window elapsing: backdate the lockout expiry.
    past = datetime.datetime.utcnow() - datetime.timedelta(minutes=1)
    auth_module._FAILED_LOGIN_ATTEMPTS["admin"] = (3, past)
    res = _login(client, "admin")
    assert res.status_code == 200
    assert res.json()["access_token"]
    assert "admin" not in auth_module._FAILED_LOGIN_ATTEMPTS, "successful login must clear tracker"
