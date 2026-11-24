# KisanMitra V2 — Deployment Smoke Test Specification & Execution Protocol

**Date:** November 24, 2026
**Auditor:** DevOps & Production Release Manager
**Target Environments:**
- Web: `https://kisanmitra.pages.dev`
- API: `https://kisanmitra-api-ewur.onrender.com`

---

## 1. Post-Deployment Verification Steps (Read-Only)

Once the local commits are pushed to `origin/release/production-deployment-pipeline`, execute these verification probes:

### A. Health & Database Probe
```bash
curl -s -i "https://kisanmitra-api-ewur.onrender.com/health"
```
*Expected Response:*
- HTTP 200 OK
- `status: "healthy"` or `"degraded"` (if external AGMARKNET is refreshing)
- `db_reachable: true`
- `model_loaded: true` (or cold start fallback 503 until archive extracted)

### B. Saturation Semantic Probe (Kolar / Tomato)
```bash
curl -s "https://kisanmitra-api-ewur.onrender.com/saturation/Kolar/Tomato?season=Rabi%202026-2027"
```
*Expected Response:*
- `has_declarations: true` or `false`
- If `has_declarations == false`, `saturation_pct` must be null or omitted, never fabricated as `0.0%`.

### C. Market Price & Forecast Probe
```bash
curl -s "https://kisanmitra-api-ewur.onrender.com/prices/predict?commodity=Tomato&market=Kolar"
```
*Expected Response:*
- If mandi record is stale (>3 days), `predicted_price: null` and `stale_data: true`.
- If anomaly detected, `anomaly_flagged: true` with dynamic crop-aware threshold.

### D. Security & CORS Probe
```bash
curl -s -I -X OPTIONS "https://kisanmitra-api-ewur.onrender.com/prices/districts" \
  -H "Origin: https://kisanmitra.pages.dev" \
  -H "Access-Control-Request-Method: GET"
```
*Expected Response:*
- HTTP 200 / 204 with `Access-Control-Allow-Origin: https://kisanmitra.pages.dev`
- Any untrusted HTTP origin must be refused.

### E. Frontend PWA Loading
Navigate to `https://kisanmitra.pages.dev` and confirm:
1. Manifest loads (`/manifest.webmanifest`).
2. Service worker registers (`/sw.js`).
3. Theme toggles correctly between light and dark modes.
4. Insights view displays saturation map without raw comment leaks.
5. Market terminal chart renders responsive axes and collapses when unpopulated.
