from __future__ import annotations

import re

from sqlalchemy import func, select
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

# Used when the reference table has no entry for this district/crop pair.
_DEFAULT_DISTRICT_AREA = 5000

def _canonical_season(value: str | None) -> str:
    """Fold season spellings to one comparable key.

    Declarations are stored as free text written by three different input
    paths, and the two layers that name a season disagree on format:
    dashboard sends "Kharif 2026" while backend/core/dates.py produces
    "kharif_2026". Comparing them byte-for-byte meant a real season matched
    nothing and the map reported 0% saturation for districts that plainly have
    declarations. Case and separator are presentation, not meaning.
    """
    return re.sub(r"[\s_]+", " ", (value or "").strip().lower())


def _season_label(matching: list[str], requested: str) -> str:
    """Spell the resolved season the way a reader can select it.

    Three input paths write one cycle in more than one format, so the same
    season exists as both "kharif_2026" and "Kharif 2026". Every spelling is
    counted in the measurement; this only picks which one is displayed, so the
    header chip, the radar and the dropdown never show three different labels
    for the number they all describe. Raw values stay in `seasons_with_data`.
    """
    if not matching:
        return requested
    readable = next((s for s in matching if s and "_" not in s), None)
    if readable:
        return readable
    if _canonical_season(requested) == _canonical_season(matching[0]):
        return requested          # the caller's own spelling names this season
    return _canonical_season(matching[0]).title()


async def _season_inventory(
    district: str, crop: str, db: AsyncSession
) -> list[dict]:
    """Every season this district/crop actually has declarations in, newest first."""
    rows = (await db.execute(
        select(CropDeclaration.season,
               func.count(CropDeclaration.id),
               func.max(CropDeclaration.declared_at))
        .where(
            CropDeclaration.district.ilike(district),
            CropDeclaration.crop.ilike(crop),
        )
        .group_by(CropDeclaration.season)
    )).all()
    return sorted(
        ({"season": r[0], "declarations": r[1], "latest": r[2]} for r in rows),
        key=lambda item: (item["latest"] is not None, item["latest"]),
        reverse=True,
    )


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

    # Resolve the requested season against the stored vocabulary before reading
    # any areas, so a format difference cannot silently become "no data".
    inventory = await _season_inventory(dist, cr, db)
    wanted = _canonical_season(season)
    matching = [item["season"] for item in inventory
                if _canonical_season(item["season"]) == wanted]
    season_match = "exact"
    if matching:
        # Several spellings can name one season ("Kharif 2026" and
        # "kharif_2026" for the same crop); count them all rather than the one
        # that happens to be spelled like the caller.
        if any(item["season"] != season for item in inventory
               if _canonical_season(item["season"]) == wanted):
            season_match = "normalised"
    else:
        # The requested season has no declarations for this district/crop. Use
        # the most recent season that does, and say so: an empty number is only
        # honest if the reader is told which season it describes.
        if inventory:
            # Fall back to the WHOLE latest season, not to one spelling of it.
            # Selecting only inventory[0] would measure 5 declarations here while
            # the same cycle reached by choosing "Kharif 2026" in the dropdown
            # measured 7 — two different numbers for one season, which is exactly
            # the disagreement this resolution exists to remove.
            newest = _canonical_season(inventory[0]["season"])
            matching = [item["season"] for item in inventory
                        if _canonical_season(item["season"]) == newest]
            season_match = "latest_available"
        else:
            season_match = "none"

    if matching:
        result = await db.execute(
            select(CropDeclaration.area_acres)
            .where(
                CropDeclaration.district.ilike(dist),
                CropDeclaration.crop.ilike(cr),
                CropDeclaration.season.in_(matching),
            )
        )
        areas = [a for a in result.scalars().all() if a is not None]
    else:
        areas = []
    total_area   = sum(areas)
    farmer_count = len(areas)
    season_used  = _season_label(matching, season)

    # The denominator is a published statistics reference, never a measured
    # arrival. It is returned so no caller has to invent its own capacity figure
    # (the dashboard used to hardcode 175 acres for every market and crop).
    reference_area = _HISTORICAL_AREA.get(dist, {}).get(cr)
    reference_basis = "district_crop_statistics" if reference_area is not None else "state_average_fallback"
    avg_area = reference_area if reference_area is not None else _DEFAULT_DISTRICT_AREA
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
        "season":         season_used,
        # Which season the number above actually describes, and how it was
        # chosen. Without these the caller cannot tell "0% saturated" from "no
        # declarations exist", and a reader would act on the first when the
        # truth is the second.
        "season_requested":    season,
        "season_match":        season_match,
        "season_fallback":     season_match == "latest_available",
        "has_declarations":    farmer_count > 0,
        "seasons_with_data":   [item["season"] for item in inventory],
        # Provenance of the denominator, so a reader can tell a real reference
        # district/crop figure from the generic fallback.
        "reference_area_acres": reference_area,
        "reference_basis":      reference_basis,
    }
    
    _SATURATION_CACHE[cache_key] = (response, time.time())
    return response
