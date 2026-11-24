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
  5. With the real artifact loaded the trained-vocabulary gate is ACTIVE and
     refuses an untrained mandi — the guard the whole forecast path depends on.

Tests 1, 2, 3 and 5 assert facts about the served artifact itself, so they are
marked `requires_served_model`: the artifact-free CI job must not run them and
the certification job must not be able to report green without running them.
Test 4 uses a throwaway in-memory artifact and therefore runs everywhere.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import joblib
import numpy as np
import pytest
from sklearn.ensemble import RandomForestRegressor

from backend.services import ml_service
from conftest import TRAINING_VOCABULARY, TRAINED_MARKET, UNTRAINED_MARKET


@pytest.fixture()
def loaded(served_model):
    """The real shipped model, loaded fresh for one test.

    `served_model` skips (loudly, naming the missing artifact) when the
    checkout has none, and `tests/conftest.py` restores every global this
    touches, so the load cannot leak into any later test.
    """
    return served_model


@pytest.mark.requires_served_model
def test_served_model_is_the_random_forest(loaded):
    assert loaded.SERVED_MODEL_PROVENANCE["algorithm"] == "RandomForestRegressor"
    assert loaded.SERVED_MODEL_PROVENANCE["n_features"] == 16
    # The shipped metadata must describe the artifact that is actually loaded.
    assert loaded.SERVED_MODEL_PROVENANCE["metadata_algorithm"] == "RandomForestRegressor"
    assert loaded.MODEL_METADATA_MATCHES is True


@pytest.mark.requires_served_model
def test_displayed_crop_mape_is_random_forest_not_catboost_median(loaded):
    # The mismatched key must no longer exist at the top level...
    assert "crop_median_mape" not in loaded.METADATA
    # ...and the values the frontend shows are the RandomForest per-crop MAPE.
    assert loaded.CROP_MAPE["Tomato"] == pytest.approx(27.73)
    assert loaded.CROP_MAPE["Onion"] == pytest.approx(28.61)
    assert loaded.CROP_MAPE["Maize"] == pytest.approx(8.49)
    # The old phantom CatBoost figures must not be what is displayed.
    assert loaded.CROP_MAPE["Tomato"] != pytest.approx(39.92)


@pytest.mark.requires_served_model
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


@pytest.mark.requires_served_model
def test_vocabulary_gate_is_active_when_the_artifact_is_loaded(loaded):
    """The coverage guard must be reporting real verdicts, not abstaining.

    `encoder_coverage()` returns `checked=False` while no encoders are loaded,
    which silently disables the gate. With the served artifact present that
    escape must be closed: a trained pair is supported, an untrained mandi is
    refused by name, and the stand-in vocabulary the rest of the suite uses is
    a subset of what the model actually knows.
    """
    assert loaded.ENCODERS is not None

    trained = loaded.encoder_coverage("Tomato", TRAINED_MARKET)
    assert trained["checked"] is True
    assert trained["supported"] is True
    assert trained["missing"] == []

    untrained = loaded.encoder_coverage("Tomato", UNTRAINED_MARKET)
    assert untrained["checked"] is True
    assert untrained["supported"] is False
    assert untrained["missing"] == ["market"]

    # The fixture vocabulary other tests rely on may not invent classes.
    for axis, classes in TRAINING_VOCABULARY.items():
        assert set(classes) <= set(loaded.supported_classes(axis)), (
            f"stand-in vocabulary has {axis} classes the served model lacks"
        )


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

    # No manual "restore by reloading the real model" step here: that call
    # raised on any checkout without artifacts (three CI errors) and, before it
    # raised, had already left the throwaway MODEL/ENCODERS/METADATA in the
    # module for every later test file. tests/conftest.py restores the snapshot
    # it took before this test ran, which works in both modes.
