# KisanMitra V2 — Release Source Baseline

**Generated:** November 24, 2026
**Auditor:** Principal Software Engineer, Security Auditor & QA Team
**Working Directory:** `/home/chandu/kisanmitra`
**Git Remote:** `https://github.com/CHANDU-M05/kisanmitra.git` (`origin`)

---

## 1. Exact Git State & Identification

| Parameter | Value |
|---|---|
| **Working Directory (`pwd`)** | `/home/chandu/kisanmitra` |
| **Current Branch** | `release/production-deployment-pipeline` |
| **Local HEAD Commit** | `b37e63cf8042d3efee95e881eb9ee154d54c4411` |
| **Remote Tracking Commit** | `f43974a20b8f8158d2bd64eb47c169d8b6f319bc` (`origin/release/production-deployment-pipeline`) |
| **Branch Divergence** | Ahead by 9 commits, behind by 0 commits (`0 9`) |
| **Index Status** | No staged changes |
| **Working Tree Modifications** | 33 tracked files modified |
| **Untracked Directories/Files** | 21 untracked release files (plus 13 excluded local artifacts) |

---

## 2. Review of the 9 Commits Ahead of Origin

These 9 commits represent verified pre-release work committed to `release/production-deployment-pipeline` locally:

1. **`b37e63c`** `feat(security): guard public AI endpoints against oversized and abusive requests (A1)`
   - Implemented `RequestGuardMiddleware` with 16KB body cap, fixed-window rate limiting (30 advisory/min, 60 conversation/min), and input semantic length validation.
2. **`0950e0f`** `fix(security): fail-closed CORS — require explicit HTTPS origins in production`
   - Enforces explicit non-wildcard HTTPS origins in production environments.
3. **`4d8811d`** `fix(forecast): crop-aware anomaly gate with non-finite hardening (P0-3)`
   - Dynamically scales anomaly spike/crash threshold using `max(30%, 1.5 * crop_mape)` to prevent false alarms on volatile crops like Tomato.
4. **`fb8fd5a`** `fix(ml): align model_metadata to the served RandomForest and guard against drift`
   - Replaced mismatched CatBoost metadata with canonical 16-feature RandomForest metadata and added runtime provenance check.
5. **`03e807b`** `test(data-refresh): DB-free regression for Ragi alias canonicalise + dedup`
   - Added DB-free unit tests verifying alias deduplication for commodity refresh.
6. **`4740111`** `fix(admin): consistent 401/403/network handling for delete & audit mutations`
   - Integrated session expiration latches and 401 redirect handlers in admin registry mutation actions.
7. **`5c7b3f6`** `feat(ui): label simulated weather, neutralize agronomist loading copy, render crop allocation`
   - Added persistent SIMULATED DATA labels on weather screen, neutralized AI loading copy, and rendered top crop allocation bars.
8. **`1fed88e`** `fix(admin): clear expired session and redirect to login on 401`
   - Handled 401 responses explicitly on the Farmers view, preventing swallowed errors and empty tables.
9. **`3fee562`** `fix(data-refresh): correct Ragi/Marigold source spellings + canonical alias dedup`
   - Fixed exact-match commodity names (`Ragi(Finger Millet)` and `Marigold(Calcutta)`) matching live data.gov.in schemas.

---

## 3. Working Tree State: Tracked Modifications (32 Files)

The 32 tracked files modified in the working tree contain verified critical bugfixes:
- **`tests/test_freshness_states.py`**: Updated static `2026-11-01` date mocks to dynamic `dt.date.today()` to respect the 3-day freshness SLA.
- **`backend/core/security.py` & `backend/routers/auth.py`**: Migrated deprecated Python `datetime.utcnow()` to timezone-aware UTC datetime.
- **`tests/test_auth_login.py`**: Fixed naive vs aware datetime comparison in lockout test.
- **`frontend/src/pages/InsightsView.jsx`**: Removed JSX comment leak (`/* Main Split Grid */`), corrected map legend labels, hover-only tooltips.
- **`frontend/src/pages/TerminalView.jsx`**: Replaced massive empty chart with adaptive collapsing layout, added accessible form labels.
- **`backend/services/farmer_service.py`**: Enforced explicit saturation semantics (`has_declarations` distinction).
- **`backend/services/scheduler.py`**: Enforced 4-tier freshness classification with advisory locking.

---

## 4. Untracked Files & Artifact Inventory

1. **Audit Documentation & Screenshots:**
   - `artifacts/deployed-audit/`
   - `artifacts/final-demo-audit/`
   - `artifacts/phase0-master-audit-2026-11-03/`
   - `artifacts/release-readiness/`
2. **Harnesses & Freshness Service:**
   - `backend/services/freshness.py` (FreshnessState, FreshnessCache, compute_freshness)
   - `frontend/src/saturationMap.js` & `frontend/tests/saturationMap.test.mjs`
   - `tests/conftest.py`, `tests/db_safety.py`, `tests/integration_manifest.txt`
   - `tests/test_db_safety.py`, `tests/test_forecast_pipeline.py`, `tests/test_freshness_states.py`, `tests/test_model_artifact_retrieval.py`
3. **Archive Checksums:**
   - `kisanmitra-base-b37e63c.tar.gz.sha256`
   - `kisanmitra-RC-worktree-2026-11-05.tar.gz.sha256`

---

## 5. Runtime Environment & Versions

| Runtime / Tool | Version | Target Production Version | Parity Status |
|---|---|---|---|
| **Python** | 3.14.8 (host / venv) | 3.12-slim (Docker) | Divergent on host; Dockerfile & CI enforce 3.12 |
| **Node.js** | v26.11.1 | v20 LTS | Host Node 26 compatible with Vite 8 |
| **NPM** | 12.2.0 | - | Functional |
| **Docker Engine** | 29.9.0 | Render Docker Runtime | Available locally |

---

## 6. Initial Release Blockers

1. **Remote Divergence:** Branch is ahead of origin by 9 commits; working tree has 32 modified files. Push is required to deploy to Render/Cloudflare.
2. **Python 3.12 Parity:** Docker container build verification required to prove compatibility with `python:3.12-slim`.
3. **Database Test Isolation:** Real PostgreSQL integration tests require an isolated disposable test database.
