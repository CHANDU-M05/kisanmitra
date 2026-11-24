# KisanMitra V2 — Test Evidence & Execution Log

**Date:** November 24, 2026
**Auditor:** QA Automation & DevOps Engineering Team
**Environment:** Linux 6.18, Python 3.14.8 (host runtime), Python 3.12.13 (verified installed via uv), Node v26.11.1, npm 12.2.0

---

## 1. Summary of Executed Test Suites

| Suite | Exact Command | Passed | Failed | Skipped / Deselected | Duration | Result |
|---|---|---|---|---|---|---|
| **Frontend Unit Tests** | `cd frontend && node --test tests/` | 55 | 0 | 0 | 5.15s | **PASS** |
| **Frontend Production Build** | `cd frontend && npm run build` | 28 precache entries | 0 | 0 | 1.18s | **PASS** |
| **Backend Unit & Logic Suite** | `venv/bin/python -m pytest tests/ -q -m "not requires_served_model and not integration_db" --ignore=tests/load --tb=line -k "not test_live_"` (task-626) | 458 | 0 | 19 deselected | 29.58s | **PASS** |
| **Security & Config Validation**| `pytest tests/test_secret_redaction.py tests/test_production_config_validation.py tests/test_cors_fail_closed.py` | 64 | 0 | 0 | 2.21s | **PASS** |
| **Model Provenance & Retrieval**| `pytest tests/test_model_artifact_retrieval.py tests/test_model_provenance.py tests/test_p0_accuracy.py` | 34 | 0 | 0 | 2.09s | **PASS** |
| **Database Safety Isolation** | `pytest tests/test_db_safety.py` | 41 | 0 | 0 | 8.49s | **PASS** |
| **Market Forecast & Routers** | `pytest tests/test_declarations_endpoint.py tests/test_prices_router_integrity.py tests/test_district_spelling_aliases.py tests/test_forecast_pipeline.py` | 46 | 0 | 0 | 1.94s | **PASS** |
| **Freshness States** | `pytest tests/test_freshness_states.py` | 40 | 0 | 0 | 1.80s | **PASS** |
| **Anomaly Gate Edge Cases (DEF-12)** | `pytest tests/test_anomaly_gate.py` | 22 | 0 | 0 | 1.36s | **PASS** |
| **Saturation Semantics (DEF-11)** | `node --test frontend/tests/saturationMap.test.mjs` | 13 | 0 | 0 | 103.9ms | **PASS** |
| **Channels & Offline RAG** | `pytest tests/test_message_handler.py tests/test_webhook_verification.py tests/test_whatsapp_price_consistency.py tests/test_rag_offline_fallback.py` | 21 | 0 | 0 | 1.38s | **PASS** |
| **Declaration Identity & Phone** | `pytest tests/test_declaration_identity.py tests/test_phone_validation.py` | 36 | 0 | 3 skipped | 1.43s | **PASS** |

---

## 2. Background Task-626 Complete Test Evidence

- **Task ID:** `task-626`
- **Exit Code:** 0
- **Total Tests Collected:** 477 items
- **Passed:** 458
- **Failed:** 0
- **Deselected:** 19 (`-k "not test_live_"`)
- **Warnings:** 3 (google-genai deprecation warning in Python 3.14, async mock unawaited warning in test probe)
- **Duration:** 29.58 seconds

---

## 3. Disclosed Sandbox Environment Limitations

1. **Python 3.12 Dependency Installation:**
   - Python 3.12.13 binary was located at `/home/chandu/.local/share/uv/python/cpython-3.12.13-linux-x86_64-gnu/bin/python3.12`.
   - `compileall.compile_dir` succeeded 100% on `backend` and `tests` under Python 3.12.
   - However, network sandbox restrictions block pip/uv from reaching `pypi.org` (HTTP 403 Forbidden), preventing creation of a fresh venv from scratch.
2. **Local PostgreSQL Service:**
   - No local PostgreSQL service is running on `localhost:5432`.
   - The test suite's `test_db_safety.py` (41 tests) passed completely, verifying that tests fail closed without connecting to unauthorized or production databases.
3. **Live TCP Socket Guard Tests (`tests/test_request_guard.py::test_live_*`):**
   - 4 live tests attempt to bind raw local TCP sockets with custom Host headers over loopback (`127.0.0.1`).
   - The execution sandbox environment intercepts raw IP HTTP connections with `400 Direct IP access is not allowed`. All 30 unit tests covering `RequestGuardMiddleware` pass.
4. **Local Docker Daemon:**
   - Docker daemon socket (`/var/run/docker.sock`) is not running/mounted in the sandbox. Docker build is enforced via GitHub Actions CI (`.github/workflows/ci.yml`).
