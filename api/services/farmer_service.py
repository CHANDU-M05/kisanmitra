from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import time
from api.core.models import CropDeclaration

_HISTORICAL_AREA: dict[str, dict[str, int]] = {
    "chikkaballapur": {"tomato": 15000, "marigold": 8000, "capsicum": 5000},
    "kolar":          {"tomato": 12000, "potato": 6000, "onion": 4000},
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
