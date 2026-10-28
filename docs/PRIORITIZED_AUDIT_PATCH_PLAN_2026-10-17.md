# KisanMitra Audit and Patch Plan — 17 October 2026

## Scope

Reviewed the supplied ZIP snapshot. This report distinguishes implemented changes in this patch from follow-up work that remains unverified or out of scope.

## Changes implemented in this patch

1. **Shared price service:** extracted the canonical price lookup/forecast logic to `backend/services/price_service.py`. The conversation handler delegates to it, and WhatsApp now uses the same service rather than maintaining its own price lookup.
2. **Removed fabricated WhatsApp spot-price defaults:** removed the `default_spots` map and generic ₹1,850 fallback from `backend/routers/webhook.py`. If no real mandi row exists, WhatsApp reports unavailable data rather than forecasting from a made-up price.
3. **Transparent fallback messaging:** WhatsApp replies include the record date; when the canonical service uses a state-level fallback, the reply identifies it as a fallback and names the source market when available.
4. **Production configuration validation:** `backend/core/config.py` now rejects known-unsafe production defaults for the signing key, database password, WhatsApp verify token, missing WhatsApp app secret, and wildcard CORS.
5. **Secret hygiene:** removed `.env`, `frontend/.env`, `frontend/.env.production`, and runtime logs from the deliverable snapshot. Updated `.gitignore` to ignore environment files while allowing `.env.example`.
6. **Regression tests:** added checks for shared WhatsApp price-service use and production configuration rejection.

## Verification performed

- `python -m py_compile` / `python -m compileall -q backend telegram_bot tests scripts`: passed.
- `PYTHONPATH=. pytest -q tests/test_production_config_validation.py tests/test_whatsapp_price_consistency.py`: **8 passed**.
- Full `PYTHONPATH=. pytest -q`: test collection is blocked by missing environment dependencies in this runner: `thefuzz`, `psycopg`, and `aiogram`. This is an environment blocker, not a passing full-suite result.

## Prioritized remaining work

### P0 — complete before production use

- **Enforce price freshness:** decide a data-owner-approved freshness SLA and return an explicit stale-data result when exceeded. Do not silently call old records today's prices.
- **Market-consistent history:** verify spot price, arrivals, and lag history use the same resolved market. Avoid substituting fabricated lag features without a degraded-data flag.
- **Model confidence:** reconcile deployed model artifacts with `model_metadata.json`; calibrate forecast intervals on held-out chronological data before presenting them as meaningful bounds.
- **Credential incident response:** rotate any real credentials that were present in the uploaded archive, including database, Telegram, WhatsApp, Gemini, and signing secrets. Removing files from this sanitized copy does not revoke credentials or erase previous copies.

### P1 — correctness and operational reliability

- Add minimum-sample guards and provenance for crop-saturation denominators.
- Correct multi-crop parsing and route market timing/sell questions away from unconstrained agronomy generation.
- Make lag features date-aware rather than assuming one record equals one day.
- Tie feedback to a stable assistant message ID.
- Apply safe Telegram Markdown fallback to every dynamic send path.
- Replace process-local rate limiting where multi-worker deployments require shared limits.

### P2 — evidence-based quality

- Verify pgvector extension, vector index, embedding backfill, and actual semantic query execution.
- Create a held-out golden set of real farmer utterances including Kannada/Kanglish, typos, ambiguity, and failed/unknown intents.
- Evaluate per-crop walk-forward error, directional accuracy, and interval coverage.
- Add channel-level end-to-end checks and metrics for stale data, fallback rates, unknown intents, and delivery failures.

## Acceptance criteria

- No user-facing forecast can be generated from an invented spot price.
- Stale data is identified and never labelled as today's price.
- All channels share the same market lookup and forecast implementation.
- State-level fallback is explicitly identified and includes source provenance where available.
- Production startup rejects unsafe defaults.
- Full tests pass in a reproducible environment, and model claims are supported by held-out evaluation.
