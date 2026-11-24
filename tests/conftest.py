"""
tests/conftest.py — suite-wide isolation for the shared ML service state.

Why this file exists
--------------------
`backend.services.ml_service` keeps the trained model, its encoders, the
user-facing MAPE/MSP tables and the readiness flags in MODULE-LEVEL globals.
`load_model()` and `train`-adjacent helpers mutate them in place, so any test
that loads an artifact — even a throwaway one written into `tmp_path` —
changes the state every later test sees. That is how
`test_p0_accuracy.py::test_price_state_fallback_is_labeled_and_dated` came to
fail only inside the full run: an earlier provenance test left a `{}` encoder
dict in `ml_service.ENCODERS`, which turns the trained-vocabulary gate from
"inactive" into "nothing is supported", and every forecast became an
`unsupported_vocabulary` refusal.

The autouse fixture below therefore snapshots and restores, for EVERY test:

  * every module global `load_model()` writes (plus `MODELS_DIR`, which tests
    repoint at temporary artifact directories),
  * `_VOCAB_CACHE`, the normalised-vocabulary memo. Its keys are built from
    `id(encoder)`, and a freed encoder's id can be handed to a later object —
    so a stale entry can silently answer for a *different* vocabulary.
    Restoring it is a correctness requirement, not tidiness,
  * `os.environ`, so a test that sets configuration cannot leak it.

Isolation is what makes the suite order-independent; it is NOT what makes a
model-identity claim. Tests that assert facts about the real served artifact
are marked `requires_served_model` and are certified by their own CI job (see
`.github/workflows/ci.yml`) — they must never be reported as passing on an
artifact-free checkout, and they must never be silently skipped into a green
build either.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from sklearn.preprocessing import LabelEncoder

# Install the connection-level database guard BEFORE any backend import so the
# shared application engine and every engine a test creates carry the
# non-negotiable PRE-connect ("do_connect") check. Import order matters:
# db_safety must patch the SQLAlchemy factories before backend.core.database
# builds its engine.
import db_safety  # tests/ is on sys.path under the pytest rootdir

db_safety.install_engine_guard()

from backend.core.config import settings
from backend.services import ml_service

# Defensive: also guard the application engine if it was imported earlier.
import backend.core.database as _database

db_safety.attach_existing(_database.engine)

# Globals written by load_model()/train-adjacent code, plus the artifact
# directory tests repoint at tmp_path. Kept as one tuple so the snapshot and
# the restore can never drift apart.
ML_GLOBALS = (
    "MODEL",
    "ENCODERS",
    "FEATURES",
    "METADATA",
    "CROP_MAPE",
    "MSP_CURRENT",
    "MODEL_STATUS",
    "MODEL_STATUS_DETAIL",
    "MODEL_METADATA_MATCHES",
    "SERVED_MODEL_PROVENANCE",
    "MODELS_DIR",
)


def snapshot_ml_service() -> dict:
    """The exact mutable state a test may change."""
    return {
        "globals": {name: getattr(ml_service, name) for name in ML_GLOBALS},
        "vocab_cache": dict(ml_service._VOCAB_CACHE),
        "environ": dict(os.environ),
    }


def restore_ml_service(state: dict) -> None:
    for name, value in state["globals"].items():
        setattr(ml_service, name, value)
    ml_service._VOCAB_CACHE.clear()
    ml_service._VOCAB_CACHE.update(state["vocab_cache"])
    os.environ.clear()
    os.environ.update(state["environ"])


@pytest.fixture(autouse=True)
def isolate_ml_service():
    """Restore every ML-service global, the vocab memo and the environment."""
    state = snapshot_ml_service()
    try:
        yield
    finally:
        restore_ml_service(state)


# ── Stand-in vocabulary (deterministic, artifact-free) ───────────────────────
# Class names and spellings mirror the served artifact so a test written
# against this fixture means the same thing on a laptop and in the
# certification job. test_model_provenance.py pins that equality whenever the
# real artifact is loaded — the stand-in may not invent a class the model does
# not have.
TRAINING_VOCABULARY = {
    "commodity": ["Brinjal", "Maize", "Onion", "Potato",
                  "Ragi (Finger Millet)", "Tomato"],
    "market": ["Arasikere", "Bangalore", "Chikkaballapur", "Davanagere",
               "Kolar", "Mysuru"],
}

# A mandi the model knows, used wherever a test must be allowed to forecast.
TRAINED_MARKET = "Chikkaballapur"
# A real, live Karnataka mandi the model was NOT trained on — the honest
# refusal case.
UNTRAINED_MARKET = "Yeshvantapur"


@pytest.fixture()
def trained_vocabulary():
    """Install fitted encoders so the vocabulary gate is genuinely ACTIVE.

    A test that only patches `MODEL` relies on `ENCODERS` happening to be None
    to reach the forecast path: with the artifact absent the coverage gate
    reports `checked=False` and passes silently. That is a test that changes
    meaning depending on the checkout. Installing an explicit encoder makes
    "this pair is supported" an asserted fact in both modes.
    """
    encoders = {axis: LabelEncoder().fit(classes)
                for axis, classes in TRAINING_VOCABULARY.items()}
    # Keys are id()-based, so drop any memo from a previous fixture instance.
    ml_service._VOCAB_CACHE.clear()
    with patch.object(ml_service, "ENCODERS", encoders):
        yield encoders
    ml_service._VOCAB_CACHE.clear()


# ── Database test safety (B2, connection-level) ──────────────────────────────
# The safety boundary lives in db_safety: an explicit disposable-test-database
# DESIGNATION (pure config — never a live probe) plus a SQLAlchemy "do_connect"
# PRE-connect guard installed at import above. The `integration_db` marker is a
# convenience for a clean local skip; the real protection is the do_connect
# listener, which refuses ANY PostgreSQL connection from ANY test, marked or
# not, BEFORE the driver opens a socket. A new DB-writing test that forgets
# `@requires_db` therefore never even reaches the network against a real store.
# There is deliberately no network probe at import/collection time: mock-only
# tests and `--collect-only` contact no DB.

# Re-exported so integration modules and regression tests read one source.
disposable_db_status = db_safety.disposable_db_status

# `requires_db` tags DB-backed tests so they SKIP (clearly reported) when no
# disposable database is authorized — e.g. a laptop with no PostgreSQL running.
requires_db = pytest.mark.integration_db


def pytest_runtest_setup(item):
    """Skip integration tests when no disposable test DB is authorized.

    This is SELECTION only — it never decides what is SAFE (the connection guard
    does, independent of this marker). In CI, where the workflow sets
    KM_TEST_DB_APPROVED=1, APP_ENV=test and KM_TEST_DB_NAME=<disposable> against
    its PostgreSQL service, the designation passes and these tests run for real.
    A target that is merely reachable, or whose name only contains the substring
    "test", is NOT authorized: designation is an exact allowlist plus host check.
    """
    if item.get_closest_marker("integration_db") is not None:
        ok, why = db_safety.disposable_db_status()
        if not ok:
            pytest.skip(f"disposable test database not authorized: {why}")


# ── Served artifact availability ─────────────────────────────────────────────
@pytest.fixture(scope="session")
def served_model_status() -> tuple[bool, str]:
    """Try the application's own artifact path once per session.

    Uses `ml_service.load_model()`, i.e. exactly what the running app does:
    present files in MODEL_DIR, otherwise the pinned MODEL_URL + MODEL_SHA256
    download. The attempt is isolated, so probing cannot perturb later tests.
    """
    state = snapshot_ml_service()
    try:
        ml_service.load_model()
        if ml_service.model_loaded():
            return True, ml_service.MODEL_STATUS_DETAIL
        return False, ml_service.MODEL_STATUS_DETAIL or "model not ready"
    except Exception as exc:                      # noqa: BLE001 - reported, not swallowed
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        restore_ml_service(state)


@pytest.fixture()
def served_model(served_model_status):
    """Load the real artifact for one test, or skip loudly when it is absent.

    The skip reason names what is missing so a log never reads as an
    unexplained pass. Skipping here is only ever a local/dev affordance: CI
    selects these tests in a dedicated job that fails when the artifact source
    is not configured, so a full skip cannot become a green build.
    """
    available, detail = served_model_status
    if not available:
        pytest.skip(
            "served model artifact unavailable "
            f"(MODEL_DIR={ml_service.MODELS_DIR}, reason: {detail}); "
            "run the model-artifact-certification CI job"
        )
    ml_service.load_model()
    return ml_service
