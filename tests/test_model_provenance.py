"""
tests/test_model_provenance.py — P0-1 regression guards.

The served artifact (`data/models/price_model.pkl`) is a 16-feature
sklearn RandomForestRegressor, but `model_metadata.json` once published a
CatBoost 36-feature model and its metrics — which the frontend then displayed
as the live model's accuracy. These tests pin the fixes:

  1. `load_model()` records the ACTUAL served model's provenance and agrees
     with the metadata (`MODEL_METADATA_MATCHES is True`).
  2. The runtime `CROP_MAPE` shown to users comes from the RandomForest
     benchmark (`crop_mape`), not the phantom CatBoost `crop_median_mape`.
  3. `/health` surfaces `model_provenance` + `model_metadata_matches` so an
     operator can see the served identity, not only "model_loaded".
  4. A metadata/model mismatch is DETECTED and the mismatched accuracy is
     NOT silently adopted (guard holds even for a totally different artifact).
"""
from __future__ import annotations

import json
from unittest.mock import patch

import joblib
import numpy as np
import pytest
from sklearn.ensemble import RandomForestRegressor

from backend.services import ml_service


@pytest.fixture()
def loaded():
    """Load the real shipped model once; leave globals in the corrected state."""
    ml_service.load_model()
    return ml_service


def test_served_model_is_the_random_forest(loaded):
    assert loaded.SERVED_MODEL_PROVENANCE["algorithm"] == "RandomForestRegressor"
    assert loaded.SERVED_MODEL_PROVENANCE["n_features"] == 16
    # The shipped metadata must describe the artifact that is actually loaded.
    assert loaded.SERVED_MODEL_PROVENANCE["metadata_algorithm"] == "RandomForestRegressor"
    assert loaded.MODEL_METADATA_MATCHES is True


def test_displayed_crop_mape_is_random_forest_not_catboost_median(loaded):
    # The mismatched key must no longer exist at the top level...
    assert "crop_median_mape" not in loaded.METADATA
    # ...and the values the frontend shows are the RandomForest per-crop MAPE.
    assert loaded.CROP_MAPE["Tomato"] == pytest.approx(27.73)
    assert loaded.CROP_MAPE["Onion"] == pytest.approx(28.61)
    assert loaded.CROP_MAPE["Maize"] == pytest.approx(8.49)
    # The old phantom CatBoost figures must not be what is displayed.
    assert loaded.CROP_MAPE["Tomato"] != pytest.approx(39.92)


def test_health_exposes_model_provenance(loaded):
    from fastapi.testclient import TestClient
    from backend.main import app

    client = TestClient(app)  # no context manager => no lifespan/scheduler
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert "model_provenance" in body
    assert body["model_provenance"]["algorithm"] == "RandomForestRegressor"
    assert body["model_metadata_matches"] is True


def test_mismatched_metadata_is_detected_and_not_adopted(tmp_path):
    """A totally different artifact + CatBoost-labelled metadata must trip the
    guard and leave the (correct) pre-existing CROP_MAPE untouched."""
    # Tiny throwaway RandomForest with 2 features so shape-guard passes.
    tiny = RandomForestRegressor(n_estimators=2, random_state=0)
    tiny.fit(np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 3.0]]), np.array([0.0, 1.0, 2.0]))
    joblib.dump(tiny, tmp_path / "price_model.pkl")
    joblib.dump({}, tmp_path / "encoders.pkl")
    fake_meta = {
        "version": "9.9.9",
        "algorithm": "CatBoostRegressor",          # deliberately wrong
        "features": ["f0", "f1"],
        "crop_mape": {"Tomato": 99.9},             # sentinel that must NOT be adopted
        "crop_msp": {"Maize": 2400.0},
    }
    (tmp_path / "model_metadata.json").write_text(json.dumps(fake_meta))

    sentinel = {"Tomato": 12.3, "Maize": 8.6}      # pretend artifact-consistent table
    with patch.object(ml_service, "MODELS_DIR", tmp_path), \
         patch.object(ml_service, "CROP_MAPE", dict(sentinel)), \
         patch.object(ml_service, "MSP_CURRENT", {}):
        ml_service.load_model()
        assert ml_service.MODEL_METADATA_MATCHES is False
        assert ml_service.SERVED_MODEL_PROVENANCE["algorithm"] == "RandomForestRegressor"
        assert ml_service.SERVED_MODEL_PROVENANCE["metadata_algorithm"] == "CatBoostRegressor"
        # The mismatched 99.9 was NOT imported; the original table is intact.
        assert ml_service.CROP_MAPE == sentinel

    # Restore the real serving model so this test cannot leak throwaway globals
    # (MODEL/FEATURES/METADATA/provenance) into later test files.
    ml_service.load_model()
