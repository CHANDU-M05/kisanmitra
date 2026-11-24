# KisanMitra V2 — Defect Register

**Date:** November 24, 2026
**Auditor:** Principal Software Architect & QA Lead

---

## 1. Defect Classification Scheme

- **P0:** Data corruption, security breach, false agricultural measurement, or critical crash.
- **P1:** Major feature unavailable, wrong calculation, or unhandled regression.
- **P2:** Non-critical functional defect, deprecation warning, or edge-case flaw.
- **P3:** Cosmetic, accessibility, or documentation error.

---

## 2. Complete Defect & Remediation Inventory

| ID | Component | Severity | Description | Remediation Applied | Verification Status |
|---|---|---|---|---|---|
| **DEF-01** | `tests/test_freshness_states.py` | P1 | Hardcoded mock date `2026-11-01` breached the 3-day SLA threshold, failing `is_stale` tests. | Updated mock to dynamic `dt.date.today()` in test cases. | **VERIFIED RESOLVED** (40/40 tests pass) |
| **DEF-02** | `tests/test_freshness_states.py` | P1 | Hardcoded mock date `2026-11-01` caused assertion failure in `refresh_once` test. | Updated all 3 `refresh_once` mock dates to dynamic date. | **VERIFIED RESOLVED** |
| **DEF-03** | `backend/core/security.py` | P2 | Deprecated `datetime.utcnow()` used in JWT token expiration calculation. | Migrated to `datetime.now(timezone.utc)`. | **VERIFIED RESOLVED** |
| **DEF-04** | `backend/routers/auth.py` | P2 | Deprecated `datetime.utcnow()` and `utcfromtimestamp()` in login lockout and token pruning. | Migrated to `datetime.now(timezone.utc)` and `fromtimestamp(..., tz=timezone.utc)`. | **VERIFIED RESOLVED** |
| **DEF-05** | `tests/test_auth_login.py` | P2 | Naive vs aware datetime comparison error (`now < lock_until`) in lockout expiry test. | Updated test backdated timestamp to timezone-aware UTC. | **VERIFIED RESOLVED** (7/7 tests pass) |
| **DEF-06** | `InsightsView.jsx` | P2 | Accidental JSX comment leak `/* Main Split Grid */` rendered as literal visible text. | Removed rogue text comment node. | **VERIFIED RESOLVED** |
| **DEF-07** | `InsightsView.jsx` | P2 | Map legend conflated OPTIMAL and SAFE; missing visual indication for unavailable data. | Legend updated to "SAFE (LOW)" and added "DATA N/A" badge. | **VERIFIED RESOLVED** |
| **DEF-08** | `TerminalView.jsx` | P2 | Giant empty chart container rendered when verified market records did not exist. | Adaptive collapsing chart container with honest compact empty state. | **VERIFIED RESOLVED** |
| **DEF-09** | `TerminalView.jsx` | P2 | Missing crop declaration acreage rendered as a misleading 0% progress bar. | Replaced with explicit "No declarations — saturation not measurable" label. | **VERIFIED RESOLVED** |
| **DEF-10** | `TerminalView.jsx` | P3 | Crop and Market select inputs lacked accessible labels and focus ring styling. | Added explicit `<label>` tags with matching `id`s and focus ring styling. | **VERIFIED RESOLVED** |
| **DEF-11** | `backend/services/farmer_service.py`| P0 | Potential conflation of 0% saturation with missing declarations. | Enforced `has_declarations: farmer_count > 0` contract; never emits 0.0% when unmeasured. | **VERIFIED RESOLVED** (13/13 frontend saturation tests pass) |
| **DEF-12** | `backend/services/price_service.py` | P0 | Fixed 30% anomaly gate triggering false crashes on volatile crops (Tomato/Marigold). | Dynamically scaled anomaly threshold to `max(30%, 1.5 * crop_mape)` with non-finite guards. | **VERIFIED RESOLVED** |
| **DEF-13** | `frontend/src/saturationMap.js` & `InsightsView.jsx` | P2 | CartoDB basemap raster tiles served diagonal "API KEY REQUIRED" watermark across Live Command Map due to CartoDB public endpoint policy change. | Replaced default raster tile provider with standard OpenStreetMap raster tiles (`https://tile.openstreetmap.org/{z}/{x}/{y}.png`) with required clickable `© OpenStreetMap contributors` attribution; preserved environment override (`VITE_MAP_TILE_URL`), offline local canvas fallback, and zero paid API dependencies. | **VERIFIED RESOLVED** (55/55 frontend tests pass; 13/13 saturation tests pass; production bundle verified clean) |
