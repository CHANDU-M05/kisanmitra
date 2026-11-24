"""
tests/test_model_artifact_retrieval.py — the artifact pipeline, offline.

`.pkl` files are not in git (`.gitignore`: `data/models/*.pkl`), so a fresh
checkout cannot read a model from the repository. The application's own answer
is `ml_service._download_and_verify_models()`: fetch `MODEL_URL`, require a
matching `MODEL_SHA256`, extract into `MODEL_DIR`, then load. That path is what
CI and the deployment targets depend on, so it is tested here with a synthetic
archive — no network, no production artifact.

Scope note, deliberately blunt: these tests certify the RETRIEVAL AND INTEGRITY
MECHANISM. They never claim anything about the identity of the served model —
the algorithm, feature count, published MAPE or fitted vocabulary of the real
artifact are asserted only in `tests/test_model_provenance.py`, under
`requires_served_model`, by the CI certification job. A synthetic stand-in
pickle cannot and does not prove that the application can obtain its real
model.

The `file://` scheme is used as the archive source because `urlopen` accepts
it: the whole fetch/verify/extract/load sequence runs exactly as it would over
HTTPS, while the test stays local and deterministic.
"""
from __future__ import annotations

import hashlib
import json
import tarfile
from pathlib import Path
from unittest.mock import patch

import joblib
import numpy as np
import pytest
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import LabelEncoder

from backend.core import config as config_module
from backend.services import ml_service

_MODEL_FILES = ("price_model.pkl", "encoders.pkl", "model_metadata.json")


def _synthetic_artifact_dir(target: Path) -> Path:
    """A tiny but internally consistent model — mechanism test material only."""
    target.mkdir(parents=True, exist_ok=True)
    model = RandomForestRegressor(n_estimators=2, random_state=0)
    model.fit(np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 3.0]]), np.array([0.0, 1.0, 2.0]))
    joblib.dump(model, target / "price_model.pkl")
    joblib.dump({"commodity": LabelEncoder().fit(["Tomato"])}, target / "encoders.pkl")
    (target / "model_metadata.json").write_text(json.dumps({
        "version": "0.0-test",
        "algorithm": "RandomForestRegressor",
        "features": ["f0", "f1"],
        "crop_mape": {"Tomato": 12.5},
    }))
    return target


def _archive_from(source_dir: Path, archive: Path, member_names=_MODEL_FILES) -> Path:
    with tarfile.open(archive, "w:gz") as tar:
        for name in member_names:
            tar.add(source_dir / name, arcname=name)
    return archive


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture()
def artifact_env(tmp_path, monkeypatch):
    """MODELS_DIR plus the download settings, pointed at scratch space."""
    models_dir = tmp_path / "models"
    monkeypatch.setattr(ml_service, "MODELS_DIR", models_dir)
    monkeypatch.setattr(config_module.settings, "model_url", "")
    monkeypatch.setattr(config_module.settings, "model_sha256", "")
    return models_dir


# ── Clear failure, never a silent unusable application ───────────────────────

def test_no_files_and_no_url_fails_with_the_missing_configuration(artifact_env):
    with pytest.raises(RuntimeError, match="MODEL_URL is not set"):
        ml_service.load_model()

    # The failure is reported, not swallowed: readiness says failed, and the
    # operator-facing detail names the configuration that is missing.
    assert ml_service.MODEL is None
    assert ml_service.model_loaded() is False
    assert ml_service.MODEL_STATUS == "failed"
    assert "MODEL_URL" in ml_service.MODEL_STATUS_DETAIL
    # A failed load is a "not available" answer for callers, not a retry-later
    # one — the distinction the freshness-aware health surface relies on.
    assert "03_train_model" in ml_service.unavailable_detail()


def test_url_without_a_pinned_digest_is_refused(artifact_env, monkeypatch):
    """A pickle executes code on load; an unverified download is never run."""
    monkeypatch.setattr(config_module.settings, "model_url",
                        "https://example.invalid/models.tar.gz")
    monkeypatch.setattr(config_module.settings, "model_sha256", "")
    with pytest.raises(RuntimeError, match="MODEL_SHA256"):
        ml_service._download_and_verify_models()
    assert not artifact_env.exists() or not ml_service.models_present()


# ── Integrity ────────────────────────────────────────────────────────────────

def test_digest_mismatch_refuses_before_anything_is_extracted(artifact_env, tmp_path, monkeypatch):
    source = _synthetic_artifact_dir(tmp_path / "src")
    archive = _archive_from(source, tmp_path / "models.tar.gz")

    monkeypatch.setattr(config_module.settings, "model_url", archive.as_uri())
    monkeypatch.setattr(config_module.settings, "model_sha256", "0" * 64)

    with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
        ml_service._download_and_verify_models()

    # Nothing from an unverified archive may reach the model directory.
    assert not any((artifact_env / name).exists() for name in _MODEL_FILES)


def test_path_traversal_member_is_rejected(artifact_env, tmp_path, monkeypatch):
    source = _synthetic_artifact_dir(tmp_path / "src")
    (source / "innocent.pkl").write_bytes(b"x")
    archive = tmp_path / "evil.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(source / "price_model.pkl", arcname="../escaped.pkl")

    monkeypatch.setattr(config_module.settings, "model_url", archive.as_uri())
    monkeypatch.setattr(config_module.settings, "model_sha256", _sha256(archive))

    with pytest.raises(RuntimeError, match="Unsafe path"):
        ml_service._download_and_verify_models()
    assert not (artifact_env.parent / "escaped.pkl").exists()


def test_archive_missing_a_required_file_is_reported(artifact_env, tmp_path, monkeypatch):
    """A verified archive that does not contain all three files is a failure."""
    source = _synthetic_artifact_dir(tmp_path / "src")
    archive = _archive_from(source, tmp_path / "partial.tar.gz",
                            member_names=("price_model.pkl",))

    monkeypatch.setattr(config_module.settings, "model_url", archive.as_uri())
    monkeypatch.setattr(config_module.settings, "model_sha256", _sha256(archive))

    with pytest.raises(RuntimeError, match="still missing"):
        ml_service._download_and_verify_models()
    assert ml_service.models_present() is False


# ── Happy path, through the application's own code ───────────────────────────

def test_verified_archive_is_fetched_verified_and_loaded(artifact_env, tmp_path, monkeypatch):
    source = _synthetic_artifact_dir(tmp_path / "src")
    archive = _archive_from(source, tmp_path / "models.tar.gz")

    monkeypatch.setattr(config_module.settings, "model_url", archive.as_uri())
    digest = _sha256(archive)
    monkeypatch.setattr(config_module.settings, "model_sha256", digest)

    ml_service.load_model()

    assert ml_service.models_present() is True
    assert ml_service.MODEL_STATUS == "ready"
    assert ml_service.model_loaded() is True
    # Provenance describes the artifact that was actually loaded.
    assert ml_service.SERVED_MODEL_PROVENANCE["algorithm"] == "RandomForestRegressor"
    assert ml_service.SERVED_MODEL_PROVENANCE["n_features"] == 2
    assert ml_service.MODEL_METADATA_MATCHES is True


def test_cached_artifacts_skip_the_download(artifact_env, tmp_path):
    """Once the files are in MODEL_DIR the app must not fetch again."""
    _synthetic_artifact_dir(artifact_env)
    with patch.object(ml_service, "_download_and_verify_models") as download:
        ml_service.load_model()
    download.assert_not_called()
    assert ml_service.model_loaded() is True
