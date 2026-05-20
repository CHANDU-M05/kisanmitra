"""
scripts/04_satellite_verify.py — GUARDRAIL 3

NDVI verification pipeline with cloud-cover fallback:
  Primary:  Sentinel-2 SR (optical, 10m) — blocked during monsoon
  Fallback: Sentinel-1 GRD (SAR, 10m)   — penetrates clouds

Flow:
  1. Attempt Sentinel-2 NDVI for the 60-day window.
  2. If <3 cloud-free observations → activate Sentinel-1 SAR path.
  3. Compute trust score from whichever source succeeded.
  4. Return structured JSON consumed by /satellite/verify endpoint.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import ee

# ── Initialize GEE ────────────────────────────────────────
ee.Initialize(project="kisanmitra-494516")

# ── Karnataka crop NDVI profiles ─────────────────────────
CROP_PROFILES: dict[str, dict] = {
    "Tomato":   {"ndvi_min": 0.35, "ndvi_max": 0.75, "months": [6,7,8,9,10,11]},
    "Potato":   {"ndvi_min": 0.30, "ndvi_max": 0.70, "months": [10,11,12,1,2]},
    "Onion":    {"ndvi_min": 0.25, "ndvi_max": 0.60, "months": [10,11,12,1]},
    "Marigold": {"ndvi_min": 0.30, "ndvi_max": 0.65, "months": [8,9,10,11]},
    "Capsicum": {"ndvi_min": 0.35, "ndvi_max": 0.70, "months": [7,8,9,10]},
}

# GUARDRAIL 3: minimum usable Sentinel-2 observations before SAR fallback
_MIN_OPTICAL_OBS = 3


# ══════════════════════════════════════════════════════════
# Sentinel-2 (optical) — primary path
# ══════════════════════════════════════════════════════════

def get_sentinel2_ndvi(
    lat: float,
    lon: float,
    days_back: int = 60,
) -> list[dict]:
    """
    Fetch cloud-filtered Sentinel-2 NDVI for a 200m buffer.
    Returns list of {date, ndvi} sorted ascending.
    """
    point  = ee.Geometry.Point([lon, lat])
    buffer = point.buffer(200)
    end    = datetime.now()
    start  = end - timedelta(days=days_back)

    collection = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(buffer)
        .filterDate(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20))
        .map(
            lambda img: img
            .normalizedDifference(["B8", "B4"])
            .rename("NDVI")
            .set("system:time_start", img.get("system:time_start"))
        )
    )

    def extract(img: ee.Image) -> ee.Feature:
        val = img.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=buffer,
            scale=10,
            maxPixels=1e9,
        ).get("NDVI")
        return ee.Feature(None, {"ndvi": val, "date": img.date().format("YYYY-MM-dd")})

    features = collection.map(extract).getInfo()
    results  = [
        {"date": f["properties"]["date"], "ndvi": round(f["properties"]["ndvi"], 4)}
        for f in features.get("features", [])
        if f["properties"].get("ndvi") is not None
    ]
    results.sort(key=lambda x: x["date"])
    return results


# ══════════════════════════════════════════════════════════
# Sentinel-1 SAR — GUARDRAIL 3 fallback
# ══════════════════════════════════════════════════════════

def get_sentinel1_sar_proxy(
    lat: float,
    lon: float,
    days_back: int = 60,
) -> list[dict]:
    """
    GUARDRAIL 3: SAR backscatter proxy when optical is cloud-blocked.

    Sentinel-1 GRD VV/VH backscatter is NOT NDVI, but provides a
    vegetation proxy that correlates with crop biomass density.

    Band selection:
      VV  — sensitive to soil moisture / surface roughness
      VH  — sensitive to vegetation volume (preferred for crops)

    The returned 'ndvi' key is labelled as a SAR proxy (−20 to 0 dB
    rescaled to 0–1) so downstream trust-score logic remains unchanged.
    Callers should check result['source'] == 'sentinel1_sar'.
    """
    point  = ee.Geometry.Point([lon, lat])
    buffer = point.buffer(200)
    end    = datetime.now()
    start  = end - timedelta(days=days_back)

    collection = (
        ee.ImageCollection("COPERNICUS/S1_GRD")
        .filterBounds(buffer)
        .filterDate(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
        .select(["VH"])
    )

    def extract_sar(img: ee.Image) -> ee.Feature:
        # VH backscatter in dB (typically −25 to −5 dB for vegetation)
        # Rescale to [0, 1] via linear map: −25 dB → 0, −5 dB → 1
        vh_db = img.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=buffer,
            scale=10,
            maxPixels=1e9,
        ).get("VH")
        return ee.Feature(None, {
            "vh_db": vh_db,
            "date":  img.date().format("YYYY-MM-dd"),
        })

    features = collection.map(extract_sar).getInfo()
    results  = []
    for f in features.get("features", []):
        props = f["properties"]
        vh_db = props.get("vh_db")
        if vh_db is None:
            continue
        # Linear rescale from dB range [−25, −5] → [0, 1]
        proxy = max(0.0, min(1.0, (vh_db + 25) / 20))
        results.append({
            "date":   props["date"],
            "ndvi":   round(proxy, 4),  # labelled 'ndvi' for schema compat
            "source": "sentinel1_sar",
        })
    results.sort(key=lambda x: x["date"])
    return results


# ══════════════════════════════════════════════════════════
# Shared processing
# ══════════════════════════════════════════════════════════

def smooth_ndvi(series: list[dict], window: int = 20) -> list[dict]:
    """Apply a centred moving-average to reduce noise."""
    if len(series) < 3:
        return series
    smoothed = []
    for i, item in enumerate(series):
        lo  = max(0, i - window // 2)
        hi  = min(len(series), i + window // 2 + 1)
        avg = sum(x["ndvi"] for x in series[lo:hi]) / (hi - lo)
        smoothed.append({**item, "ndvi": round(avg, 4)})
    return smoothed


def compute_trust_score(
    series: list[dict],
    crop: str,
    source: str = "sentinel2",
) -> tuple[float, str]:
    """
    Score 0.0–1.0 comparing the NDVI/SAR proxy against the crop profile.

    SAR scores are penalised by 0.1 to reflect lower confidence vs optical.
    """
    if not series:
        return 0.0, "No satellite data available for this location"

    profile      = CROP_PROFILES.get(crop, CROP_PROFILES["Tomato"])
    current_month = datetime.now().month
    recent_vals  = [x["ndvi"] for x in series[-3:]]
    avg_val      = sum(recent_vals) / len(recent_vals)

    # Component 1: value range match (0–0.5)
    lo, hi = profile["ndvi_min"], profile["ndvi_max"]
    if lo <= avg_val <= hi:
        range_score = 0.5
    elif avg_val < lo:
        range_score = max(0.0, 0.5 - (lo - avg_val) * 2)
    else:
        range_score = max(0.0, 0.5 - (avg_val - hi) * 2)

    # Component 2: season match (0–0.3)
    season_score = 0.3 if current_month in profile["months"] else 0.1

    # Component 3: upward trend (0–0.2)
    if len(series) >= 5:
        early = sum(x["ndvi"] for x in series[:3]) / 3
        late  = sum(x["ndvi"] for x in series[-3:]) / 3
        trend_score = 0.2 if late > early else 0.1
    else:
        trend_score = 0.1

    total = round(range_score + season_score + trend_score, 2)

    # GUARDRAIL 3: SAR proxy confidence penalty
    if source == "sentinel1_sar":
        total = max(0.0, total - 0.10)

    total = min(total, 1.0)

    if total >= 0.7:
        msg = f"High confidence — {'NDVI' if source == 'sentinel2' else 'SAR proxy'} {avg_val:.2f} matches {crop} profile"
    elif total >= 0.4:
        msg = f"Moderate confidence — {'NDVI' if source == 'sentinel2' else 'SAR proxy'} {avg_val:.2f} partially matches {crop} profile"
    else:
        msg = f"Low confidence — {'NDVI' if source == 'sentinel2' else 'SAR proxy'} {avg_val:.2f} does not match {crop} profile"

    return total, msg


# ══════════════════════════════════════════════════════════
# Main pipeline
# ══════════════════════════════════════════════════════════

def verify_declaration(
    lat: float,
    lon: float,
    crop: str,
    farmer_name: str = "Farmer",
) -> Optional[dict]:
    """
    Full satellite verification with GUARDRAIL 3 cloud-cover fallback.

    Returns a structured dict consumed by the /satellite/verify endpoint.
    """
    print(f"\n{'='*55}")
    print("KisanMitra — Satellite Verification")
    print(f"{'='*55}")
    print(f"Farmer: {farmer_name}  |  Crop: {crop}  |  GPS: {lat}, {lon}")
    print(f"{'='*55}")

    # ── Step 1: Sentinel-2 (optical) ──────────────────────
    print("\nStep 1: Fetching Sentinel-2 imagery (cloud-filter < 20%) ...")
    try:
        s2_series = get_sentinel2_ndvi(lat, lon, days_back=60)
        print(f"  Found {len(s2_series)} cloud-free observations")
    except Exception as exc:
        print(f"  GEE Sentinel-2 error: {exc}")
        s2_series = []

    # ── Step 2: GUARDRAIL 3 — SAR fallback ────────────────
    source = "sentinel2"
    series = s2_series

    if len(s2_series) < _MIN_OPTICAL_OBS:
        print(
            f"\n  ⚠ Only {len(s2_series)} optical obs — below threshold ({_MIN_OPTICAL_OBS})."
            f"\n  Activating GUARDRAIL 3: Sentinel-1 SAR fallback ..."
        )
        try:
            sar_series = get_sentinel1_sar_proxy(lat, lon, days_back=60)
            print(f"  SAR: found {len(sar_series)} observations")
            if sar_series:
                series = sar_series
                source = "sentinel1_sar"
            else:
                print("  SAR also returned no data — flagging for manual review.")
        except Exception as exc:
            print(f"  SAR error: {exc}")

    if not series:
        return {
            "trust_score": 0.0,
            "status":      "NO_DATA",
            "message":     "No usable satellite data (optical or SAR). Manual review required.",
            "source":      "none",
        }

    # ── Step 3: Smooth + score ─────────────────────────────
    print(f"\nStep 2: Smoothing ({source}) time series ...")
    smoothed = smooth_ndvi(series, window=20)
    for obs in smoothed[-3:]:
        label = "NDVI" if source == "sentinel2" else "SAR proxy"
        print(f"  {obs['date']}:  {label} = {obs['ndvi']}")

    print("\nStep 3: Computing trust score ...")
    trust, message = compute_trust_score(smoothed, crop, source)

    status = "VERIFIED" if trust >= 0.7 else ("PARTIAL" if trust >= 0.4 else "FLAGGED")
    emoji  = {"VERIFIED": "✓", "PARTIAL": "~", "FLAGGED": "✗"}[status]

    result = {
        "farmer":      farmer_name,
        "crop":        crop,
        "lat":         lat,
        "lon":         lon,
        "trust_score": trust,
        "status":      status,
        "message":     message,
        "source":      source,           # sentinel2 | sentinel1_sar | none
        "ndvi_obs":    len(series),
        "latest_ndvi": smoothed[-1]["ndvi"] if smoothed else None,
        "verified_at": datetime.now().isoformat(),
    }

    print(f"\n{'='*55}")
    print(f"  {emoji}  {status}  |  Score: {trust}  |  Source: {source}")
    print(f"  {message}")
    print(f"{'='*55}\n")
    return result


# ── CLI entry point ───────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) == 5:
        r = verify_declaration(
            lat=float(sys.argv[1]),
            lon=float(sys.argv[2]),
            crop=sys.argv[3],
            farmer_name=sys.argv[4],
        )
    else:
        r = verify_declaration(
            lat=13.4355, lon=77.7315,
            crop="Tomato", farmer_name="Raju (Test)",
        )
    if r:
        print("Full result JSON:")
        print(json.dumps(r, indent=2))
