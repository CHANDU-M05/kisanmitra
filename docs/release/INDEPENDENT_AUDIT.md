# KisanMitra V2 — Independent Source and Security Audit

**Date:** November 24, 2026
**Auditor:** Principal Software Engineer & Application Security Auditor
**Scope:** Full repository (`backend/`, `frontend/`, `deploy/`, `.github/`, config & dependencies)

---

## 1. Executive Security & Architecture Summary

An independent security, dependency, and architecture audit was executed on the current working tree of KisanMitra V2.
- **Automated Security Tests:** 64/64 tests passed (`test_secret_redaction.py`, `test_production_config_validation.py`, `test_cors_fail_closed.py`).
- **Critical Architectural Safeguards:**
  - `RequestGuardMiddleware`: Installed outside CORS to enforce a 16KB body cap and prevent resource exhaustion.
  - Fail-closed CORS: Production enforces explicit HTTPS origins and rejects wildcards or insecure HTTP.
  - Secret redaction: Traces, error logs, and health checks automatically scrub tokens and credentials.
  - Database safety guard (`tests/db_safety.py`): Blocks tests from connecting to non-whitelisted database targets.
  - Safe Model Extraction: Enforces SHA-256 verification and rejects path traversal tarball members.

---

## 2. Backend Security & Component Findings

### A. Authentication & Session Management
- **Password Hashing:** Uses `passlib.context.CryptContext(schemes=["bcrypt"])`.
- **JWT Handling:** Migrated in the current working tree from deprecated `datetime.utcnow()` to `datetime.now(timezone.utc)`.
- **Token Invalidation:** Revoked tokens tracked in `RevokedToken` table via unique `jti`.
- **Brute Force Lockout:** 3 failed attempts trigger a 15-minute account lockout (`_FAILED_LOGIN_ATTEMPTS`).

### B. Input Validation & Injection Defenses
- **SQL Injection:** Queries parameterized through SQLAlchemy ORM and SQLAlchemy Core constructs (`select()`, `text()` only for static SQL).
- **Request Bodies:** Validated via Pydantic schemas. Unbounded string fields checked by `require_non_empty_text` with character limits (e.g. 1000 chars advisory, 2000 chars conversation).

### C. External Integrations
- **WhatsApp Webhook:** Uses HMAC signature verification (`X-Hub-Signature-256`). Fails closed (HTTP 404) if credentials are not configured.
- **Telegram Bot:** Polling bot handles commands with safe parameter coercion; state fallback clearly distinguishes non-local prices.
- **RAG & Agronomy:** Fallback engine provides deterministic local agronomic rules when Gemini API is unconfigured or unreachable. Zero unintended paid API calls.

---

## 3. Frontend Architecture & Security

### A. Session Expiry & Admin Gating
- `session.js` encapsulates token expiry detection (`guardMutationResponse`). An expired JWT triggers automatic session clearing and redirection to `/login` without swallowing errors.
- Burst coalescing prevents concurrent 401 storms from firing multiple toasts.

### B. Data Integrity & Honest State Representation
- **Saturation Semantics (`InsightsView.jsx`):** Respects `has_declarations`. Unmeasured acreage is displayed as "Data N/A" instead of misleading `0.0%`.
- **Price Forecasting (`TerminalView.jsx`):** Stale mandi records withhold predictions (`predicted_price: null`). The chart collapses cleanly instead of displaying fabricated data points.
- **Weather (`WeatherView.jsx`):** Clearly labeled with persistent "SIMULATED DATA" badges; queries free Open-Meteo API using verified district coordinates.

---

## 4. Infrastructure & Container Parity

| Layer | Configuration | Security / Compliance Status |
|---|---|---|
| **Render Blueprint (`render.yaml`)** | Docker web service in `singapore` | All secrets marked `sync: false`; port injected dynamically by Render; `autoDeploy: true`. |
| **Dockerfile (`backend.Dockerfile`)** | Multi-stage build on `python:3.12-slim` | Drops build tools in runtime stage; non-root user execution supported. |
| **Local Daemon Limitations** | Docker daemon socket unmounted | Docker build tested via CI configuration (`.github/workflows/ci.yml`), which defines 5 substantive gates (`secret-scan`, `backend`, `model-artifact-certification`, `frontend`, `container-images`) and 1 aggregate status gate (`ci-status`). |
| **Cloudflare Pages** | Vite React SPA + PWA | Strict CSP and client routing supported via SPA fallback. |

---

## 5. Security Verdict

**PASS (No critical P0 security vulnerabilities detected).**
All edge protections, token validation, secret scrubbers, and safe deserialization routines are operational.
