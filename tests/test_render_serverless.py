"""
tests/test_render_serverless.py — behaviour added for the Render + Neon target.

Covers the pieces that must hold before a cold start can be trusted on a
serverless, ephemeral host: driver-correct SSL options, small/recycled pools,
the bounded connect retry, model-readiness reporting, the verified-download
gate, and the Dockerfile command Render relies on. No database or network is
required — each test drives a unit directly.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.core import config as config_module
from backend.core.config import Settings
from backend.services import ml_service


# ── SSL option parsing (psycopg3 wants libpq `sslmode`, off by default) ───────
def test_sslmode_absent_by_default_keeps_local_behaviour():
    s = Settings(_env_file=None, db_sslmode="")
    assert s.db_connect_args == {}


def test_sslmode_is_passed_as_libpq_connect_kwarg():
    s = Settings(_env_file=None, db_sslmode="require")
    assert s.db_connect_args == {"sslmode": "require"}


def test_settings_read_db_sslmode_from_environment(monkeypatch):
    monkeypatch.setenv("DB_SSLMODE", "require")
    assert Settings(_env_file=None).db_sslmode == "require"


# ── Pool sizing for a scale-to-zero host ─────────────────────────────────────
def test_pool_recycle_default_is_short_for_serverless_proxy():
    # A pooled connection older than the recycle interval is discarded and
    # reopened, so a compute that resumed after idle is not handed a dead socket.
    assert Settings(_env_file=None).db_pool_recycle == 300


def test_engine_has_pre_ping_and_recycle():
    from backend.core import database

    pool = database.engine.pool
    assert pool._pre_ping is True
    assert pool._recycle == config_module.settings.db_pool_recycle


# ── Connect retry exists and is bounded ──────────────────────────────────────
def test_connect_retry_settings_are_positive_and_bounded():
    s = Settings(_env_file=None)
    assert 1 <= s.db_connect_retries <= 10
    assert 0.0 < s.db_connect_backoff_seconds <= 10.0


@pytest.mark.asyncio
async def test_ensure_database_reachable_gives_up_without_raising(monkeypatch):
    from backend.core import database

    class _Boom:
        async def __aenter__(self):
            raise RuntimeError("neon asleep")

        async def __aexit__(self, *exc):
            return False

    class _BoomEngine:
        def connect(self):
            return _Boom()

    # engine.connect is a read-only attribute on AsyncEngine, so swap the
    # module-level engine the helper closes over instead.
    monkeypatch.setattr(database, "engine", _BoomEngine())
    # Retries are bounded and the helper returns False rather than propagating.
    assert await database.ensure_database_reachable() is False


# ── Model readiness reporting ────────────────────────────────────────────────
def test_model_loaded_false_while_loading():
    original = (ml_service.MODEL, ml_service.MODEL_STATUS)
    try:
        ml_service.MODEL = None
        ml_service.MODEL_STATUS = "loading"
        assert ml_service.model_loaded() is False
        assert "loading" in ml_service.unavailable_detail().lower()
    finally:
        ml_service.MODEL, ml_service.MODEL_STATUS = original


def test_unavailable_detail_distinguishes_failure_from_loading():
    original = (ml_service.MODEL, ml_service.MODEL_STATUS)
    try:
        ml_service.MODEL = None
        ml_service.MODEL_STATUS = "failed"
        assert "03_train_model" in ml_service.unavailable_detail()
    finally:
        ml_service.MODEL, ml_service.MODEL_STATUS = original


# ── Verified model download refuses unverified pickles ───────────────────────
def test_download_refuses_when_hash_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(ml_service, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(config_module.settings, "model_url", "https://example.invalid/m.tar.gz")
    monkeypatch.setattr(config_module.settings, "model_sha256", "")
    with pytest.raises(RuntimeError, match="MODEL_SHA256"):
        ml_service._download_and_verify_models()


def test_download_refuses_when_no_url_and_no_files(monkeypatch, tmp_path):
    monkeypatch.setattr(ml_service, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(config_module.settings, "model_url", "")
    with pytest.raises(RuntimeError, match="MODEL_URL is not set"):
        ml_service._download_and_verify_models()


def test_models_present_requires_all_three(monkeypatch, tmp_path):
    monkeypatch.setattr(ml_service, "MODELS_DIR", tmp_path)
    assert ml_service.models_present() is False
    for name in ("price_model.pkl", "encoders.pkl", "model_metadata.json"):
        (tmp_path / name).write_bytes(b"x")
    assert ml_service.models_present() is True


@pytest.mark.asyncio
async def test_build_features_with_few_price_rows(monkeypatch):
    # Regression (found in the Render-shaped container sim): a local
    # `from datetime import date` inside one branch made `date` function-local,
    # so days_since_last_report raised UnboundLocalError whenever a market had
    # fewer than 3 stored prices — exactly a freshly restored Neon database.
    from datetime import datetime, timezone

    class _Res:
        def scalars(self):
            return self

        def all(self):
            return [45.0]

        def scalar_one_or_none(self):
            return datetime.now(timezone.utc)

    class _Db:
        async def execute(self, *a, **k):
            return _Res()

    monkeypatch.setattr(ml_service, "ENCODERS", None)
    df = await ml_service.build_features(
        current_price=45.0, arrivals=10.0, month=10,
        commodity="tomato", market="Bangalore", db=_Db(),
    )
    assert len(df) == 1


# ── Render-shaped Dockerfile command ─────────────────────────────────────────
def test_dockerfile_binds_port_and_defaults_to_one_worker():
    dockerfile = (
        Path(__file__).resolve().parents[1] / "deploy" / "docker" / "backend.Dockerfile"
    ).read_text()
    # Render supplies PORT; the command must honour it with a local default.
    assert "--bind 0.0.0.0:${PORT:-8000}" in dockerfile
    # 512 MB cannot fit two model-loaded workers; the image default is one.
    assert "WEB_CONCURRENCY=1" in dockerfile
    # Recycling stays for memory hygiene on a single long-lived worker.
    assert "--max-requests" in dockerfile
