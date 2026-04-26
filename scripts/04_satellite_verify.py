import ee
import json
import math
from datetime import datetime, timedelta

# ── Initialize GEE ────────────────────────────────────────
ee.Initialize(project='kisanmitra-494516')

# ── Karnataka crop NDVI profiles ─────────────────────────
# Format: [min_ndvi, max_ndvi, peak_month_start, peak_month_end]
CROP_PROFILES = {
    "Tomato":   {"ndvi_min": 0.35, "ndvi_max": 0.75, "months": [6, 7, 8, 9, 10, 11]},
    "Potato":   {"ndvi_min": 0.30, "ndvi_max": 0.70, "months": [10, 11, 12, 1, 2]},
    "Onion":    {"ndvi_min": 0.25, "ndvi_max": 0.60, "months": [10, 11, 12, 1]},
    "Marigold": {"ndvi_min": 0.30, "ndvi_max": 0.65, "months": [8, 9, 10, 11]},
    "Capsicum": {"ndvi_min": 0.35, "ndvi_max": 0.70, "months": [7, 8, 9, 10]},
}

def get_sentinel2_ndvi(lat, lon, days_back=60):
    """
    Fetch Sentinel-2 NDVI for a 200m radius around GPS point.
    Returns list of (date, ndvi) tuples.
    """
    point = ee.Geometry.Point([lon, lat])
    buffer = point.buffer(200)  # 200m radius

    end_date   = datetime.now()
    start_date = end_date - timedelta(days=days_back)

    collection = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(buffer)
        .filterDate(start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20))
        .map(lambda img: img.normalizedDifference(["B8", "B4"])
                           .rename("NDVI")
                           .set("system:time_start", img.get("system:time_start")))
    )

    # Get NDVI values
    def extract_ndvi(img):
        ndvi_val = img.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=buffer,
            scale=10,
            maxPixels=1e9
        ).get("NDVI")
        return ee.Feature(None, {
            "ndvi": ndvi_val,
            "date": img.date().format("YYYY-MM-dd")
        })

    features = collection.map(extract_ndvi).getInfo()
    results  = []

    for f in features.get("features", []):
        props = f.get("properties", {})
        if props.get("ndvi") is not None:
            results.append({
                "date": props["date"],
                "ndvi": round(props["ndvi"], 4)
            })

    results.sort(key=lambda x: x["date"])
    return results

def smooth_ndvi(ndvi_series, window=20):
    """Apply 20-day moving average to NDVI time series."""
    if len(ndvi_series) < 3:
        return ndvi_series
    smoothed = []
    for i, item in enumerate(ndvi_series):
        start = max(0, i - window // 2)
        end   = min(len(ndvi_series), i + window // 2 + 1)
        avg   = sum(x["ndvi"] for x in ndvi_series[start:end]) / (end - start)
        smoothed.append({"date": item["date"], "ndvi": round(avg, 4)})
    return smoothed

def compute_trust_score(ndvi_series, crop, lat):
    """
    Compare NDVI signature against crop profile.
    Returns trust score 0.0 to 1.0.
    """
    if not ndvi_series:
        return 0.0, "No satellite data available for this location"

    profile = CROP_PROFILES.get(crop, CROP_PROFILES["Tomato"])
    current_month = datetime.now().month

    # Recent NDVI — last 3 observations
    recent_ndvi = [x["ndvi"] for x in ndvi_series[-3:]]
    avg_ndvi    = sum(recent_ndvi) / len(recent_ndvi)

    # Score 1: NDVI range match (0 to 0.5)
    ndvi_min = profile["ndvi_min"]
    ndvi_max = profile["ndvi_max"]
    if ndvi_min <= avg_ndvi <= ndvi_max:
        range_score = 0.5
    elif avg_ndvi < ndvi_min:
        gap = ndvi_min - avg_ndvi
        range_score = max(0, 0.5 - (gap * 2))
    else:
        gap = avg_ndvi - ndvi_max
        range_score = max(0, 0.5 - (gap * 2))

    # Score 2: Season match (0 to 0.3)
    season_score = 0.3 if current_month in profile["months"] else 0.1

    # Score 3: NDVI trend — is it growing? (0 to 0.2)
    if len(ndvi_series) >= 5:
        early = sum(x["ndvi"] for x in ndvi_series[:3]) / 3
        late  = sum(x["ndvi"] for x in ndvi_series[-3:]) / 3
        trend_score = 0.2 if late > early else 0.1
    else:
        trend_score = 0.1

    total = round(range_score + season_score + trend_score, 2)

    if total >= 0.7:
        message = f"High confidence — NDVI {avg_ndvi:.2f} matches {crop} profile"
    elif total >= 0.4:
        message = f"Moderate confidence — NDVI {avg_ndvi:.2f} partially matches {crop} profile"
    else:
        message = f"Low confidence — NDVI {avg_ndvi:.2f} does not match {crop} profile"

    return min(total, 1.0), message

def verify_declaration(lat, lon, crop, farmer_name="Test Farmer"):
    """
    Full satellite verification pipeline for a farmer declaration.
    """
    print(f"\n{'='*55}")
    print(f"KisanMitra — Satellite Verification")
    print(f"{'='*55}")
    print(f"Farmer:     {farmer_name}")
    print(f"Crop:       {crop}")
    print(f"GPS:        {lat}, {lon}")
    print(f"{'='*55}")

    print("\nStep 1: Fetching Sentinel-2 imagery...")
    try:
        ndvi_series = get_sentinel2_ndvi(lat, lon, days_back=60)
        print(f"  Found {len(ndvi_series)} cloud-free observations")
    except Exception as e:
        print(f"  GEE Error: {e}")
        return None

    if not ndvi_series:
        print("  No usable imagery found — flagging for manual review")
        return {"trust_score": 0.0, "status": "NO_DATA", "message": "No satellite data"}

    print("\nStep 2: Applying 20-day NDVI smoothing...")
    smoothed = smooth_ndvi(ndvi_series, window=20)
    print(f"  Latest NDVI values:")
    for obs in smoothed[-3:]:
        print(f"    {obs['date']}: {obs['ndvi']}")

    print("\nStep 3: Computing trust score...")
    trust_score, message = compute_trust_score(smoothed, crop, lat)

    if trust_score >= 0.7:
        status = "VERIFIED"
        emoji  = "✓"
    elif trust_score >= 0.4:
        status = "PARTIAL"
        emoji  = "~"
    else:
        status = "FLAGGED"
        emoji  = "✗"

    result = {
        "farmer":      farmer_name,
        "crop":        crop,
        "lat":         lat,
        "lon":         lon,
        "trust_score": trust_score,
        "status":      status,
        "message":     message,
        "ndvi_obs":    len(ndvi_series),
        "latest_ndvi": smoothed[-1]["ndvi"] if smoothed else None,
        "verified_at": datetime.now().isoformat(),
    }

    print(f"\n{'='*55}")
    print(f"  {emoji} RESULT: {status}")
    print(f"  Trust Score: {trust_score}")
    print(f"  {message}")
    print(f"{'='*55}")

    return result

# ── Test with Chikkaballapur coordinates ─────────────────
if __name__ == "__main__":
    # Chikkaballapur tomato farm coordinates
    result = verify_declaration(
        lat=13.4355,
        lon=77.7315,
        crop="Tomato",
        farmer_name="Raju (Test)"
    )
    if result:
        print("\nFull result JSON:")
        print(json.dumps(result, indent=2))

# ── CLI entry point ───────────────────────────────────────
import sys
if len(sys.argv) == 5:
    lat  = float(sys.argv[1])
    lon  = float(sys.argv[2])
    crop = sys.argv[3]
    name = sys.argv[4]
    result = verify_declaration(lat, lon, crop, name)
    if result:
        print("\nFull result JSON:")
        print(json.dumps(result, indent=2))
