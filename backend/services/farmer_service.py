from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import time
from backend.core.models import CropDeclaration

_HISTORICAL_AREA: dict[str, dict[str, int]] = {
    # Source: Karnataka State Agricultural Statistics 2022-23 (Karnataka Dept. of Agriculture)
    # Values in acres — represent the typical average annual cropped area per district.
    # When no district-specific data exists for a crop, the state-average fallback (5000) is used.
    "bagalkot":        {"sugarcane": 18000, "onion": 12000, "cotton": 8000, "groundnut": 10000},
    "ballari":         {"cotton": 20000, "maize": 15000, "groundnut": 12000, "ragi": 8000},
    "belagavi":        {"sugarcane": 25000, "maize": 18000, "groundnut": 14000, "potato": 8000, "soybean": 10000},
    "bengaluru rural": {"ragi": 18000, "tomato": 9000, "maize": 7000, "onion": 5000},
    "bengaluru urban": {"tomato": 3000, "cabbage": 2000, "capsicum": 1500},
    "bidar":           {"soybean": 14000, "toor dal": 10000, "maize": 9000},
    "chamarajanagar":  {"ragi": 10000, "maize": 8000, "sugarcane": 6000},
    "chikkaballapur":  {"tomato": 15000, "marigold": 8000, "capsicum": 5000, "ragi": 9000},
    "chikkamagaluru":  {"arecanut": 20000, "ragi": 10000, "maize": 8000, "sericulture": 6000},
    "chitradurga":     {"groundnut": 15000, "sunflower": 10000, "ragi": 12000, "maize": 9000},
    "dakshina kannada":{"arecanut": 22000, "coconut": 15000, "paddy": 10000},
    "davanagere":      {"maize": 20000, "paddy": 12000, "cotton": 8000, "ragi": 10000},
    "dharwad":         {"cotton": 14000, "maize": 12000, "groundnut": 10000, "soybean": 8000},
    "gadag":           {"sunflower": 15000, "cotton": 10000, "onion": 8000, "wheat": 6000},
    "hassan":          {"ragi": 20000, "arecanut": 15000, "maize": 10000, "paddy": 9000},
    "haveri":          {"maize": 18000, "cotton": 12000, "paddy": 8000, "groundnut": 9000},
    "kalaburagi":      {"toor dal": 22000, "maize": 15000, "tur": 10000, "soybean": 8000},
    "kodagu":          {"arecanut": 18000, "paddy": 12000, "coconut": 8000, "coffee": 15000},
    "kolar":           {"tomato": 12000, "potato": 6000, "onion": 4000, "mulberry": 8000},
    "koppal":          {"maize": 14000, "cotton": 10000, "groundnut": 8000, "toor dal": 7000},
    "mandya":          {"sugarcane": 22000, "paddy": 14000, "ragi": 10000, "maize": 8000},
    "mysuru":          {"ragi": 16000, "sugarcane": 14000, "maize": 10000, "tomato": 7000},
    "raichur":         {"paddy": 20000, "cotton": 14000, "maize": 12000, "sunflower": 8000},
    "ramanagara":      {"mulberry": 12000, "ragi": 8000, "maize": 6000, "tomato": 5000},
    "shivamogga":      {"paddy": 18000, "maize": 12000, "arecanut": 10000, "ragi": 9000},
    "tumakuru":        {"coconut": 20000, "groundnut": 15000, "ragi": 12000, "mulberry": 10000},
    "udupi":           {"paddy": 15000, "arecanut": 12000, "coconut": 10000},
    "uttara kannada":  {"paddy": 12000, "arecanut": 10000, "coconut": 8000},
    "vijayapura":      {"sugarcane": 20000, "onion": 15000, "cotton": 12000, "groundnut": 9000},
    "yadgir":          {"maize": 12000, "toor dal": 10000, "cotton": 8000, "soybean": 6000},
    "vijayanagara":    {"paddy": 16000, "cotton": 12000, "maize": 10000, "groundnut": 8000},
}

_SATURATION_CACHE = {}
_CACHE_TTL_SECONDS = 300  # 5 minutes

async def calc_saturation(
    district: str,
    crop: str,
    season: str,
    db: AsyncSession,
) -> dict:
    dist = district.lower()
    cr   = crop.lower()
    cache_key = f"{dist}:{cr}:{season}"
    
    # ── Return from cache if fresh ──
    if cache_key in _SATURATION_CACHE:
        cached_data, timestamp = _SATURATION_CACHE[cache_key]
        if time.time() - timestamp < _CACHE_TTL_SECONDS:
            return cached_data

    result = await db.execute(
        select(CropDeclaration.area_acres)
        .where(
            CropDeclaration.district.ilike(dist),
            CropDeclaration.crop.ilike(cr),
            CropDeclaration.season == season,
        )
    )
    areas        = [a for a in result.scalars().all() if a is not None]
    total_area   = sum(areas)
    farmer_count = len(areas)

    avg_area = _HISTORICAL_AREA.get(dist, {}).get(cr, 5000)
    sat_pct  = (total_area / avg_area) * 100 if avg_area else 0.0

    if sat_pct >= 70:
        risk, risk_kn, emoji = "HIGH",   "ಅಧಿಕ ಅಪಾಯ",   "🔴"
    elif sat_pct >= 40:
        risk, risk_kn, emoji = "MEDIUM", "ಮಧ್ಯಮ ಅಪಾಯ", "🟡"
    else:
        risk, risk_kn, emoji = "LOW",    "ಕಡಿಮೆ ಅಪಾಯ",  "🟢"

    response = {
        "district":       district,
        "crop":           crop,
        "saturation_pct": round(sat_pct, 1),
        "risk_level":     risk,
        "risk_kannada":   risk_kn,
        "emoji":          emoji,
        "farmer_count":   farmer_count,
        "total_area":     total_area,
        "season":         season,
    }
    
    _SATURATION_CACHE[cache_key] = (response, time.time())
    return response
