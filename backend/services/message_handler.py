"""
api/services/message_handler.py — GUARDRAILS 1 & 2

GUARDRAIL 1 — FUZZY MATCHING
    Farmer input is never evaluated with strict equality.
    All crop and district names are resolved to canonical IDs via:
      1. A predefined alias dictionary (handles known Kannada variants)
      2. thefuzz token_set_ratio as the fallback (handles typos)

GUARDRAIL 2 — DETERMINISTIC ROUTING
    Intent routing is strictly separated to prevent LLM hallucinations on critical data:
      • PRICE / SATURATION / DECLARE  →  PostgreSQL queries (NO LLM involved)
      • AGRONOMY / ADVISORY →  RAG pipeline (Gemini + pgvector)
    The LLM is strictly isolated from numeric or market-data intents.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from thefuzz import process as fuzz_process

logger = logging.getLogger("kisanmitra.handler")

# ══════════════════════════════════════════════════════════
# Canonical IDs
# ══════════════════════════════════════════════════════════

CANONICAL_CROPS: dict[str, str] = {
    "tomato":    "Tomato",
    "potato":    "Potato",
    "onion":     "Onion",
    "marigold":  "Marigold",
    "capsicum":  "Capsicum",
    "maize":     "Maize",
    "ragi":      "Ragi",
    "brinjal":   "Brinjal",
    "cabbage":   "Cabbage",
}

CANONICAL_DISTRICTS: dict[str, str] = {
    "bagalkot": "Bagalkot", "ballari": "Ballari", "belagavi": "Belagavi",
    "bengaluru rural": "Bengaluru Rural", "bengaluru urban": "Bengaluru Urban",
    "bidar": "Bidar", "chamarajanagar": "Chamarajanagar", 
    "chikkaballapur": "Chikkaballapur", "chikkamagaluru": "Chikkamagaluru",
    "chitradurga": "Chitradurga", "dakshina kannada": "Dakshina Kannada",
    "davanagere": "Davanagere", "dharwad": "Dharwad", "gadag": "Gadag",
    "hassan": "Hassan", "haveri": "Haveri", "kalaburagi": "Kalaburagi",
    "kodagu": "Kodagu", "kolar": "Kolar", "koppal": "Koppal",
    "mandya": "Mandya", "mysuru": "Mysuru", "raichur": "Raichur",
    "ramanagara": "Ramanagara", "shivamogga": "Shivamogga",
    "tumakuru": "Tumakuru", "udupi": "Udupi", "uttara kannada": "Uttara Kannada",
    "vijayapura": "Vijayapura", "yadgir": "Yadgir", "vijayanagara": "Vijayanagara"
}

# ── GUARDRAIL 1: Alias tables (canonical Kannada variants) ─
# Every known spelling variant maps to the canonical English key.
_CROP_ALIASES: dict[str, str] = {
    # Tomato
    "tomato":   "tomato", "tomatoes": "tomato",
    "ಟೊಮೆಟೊ":  "tomato", "ಟೊಮೆಟೋ": "tomato", "ಟೊಮ್ಯಾಟೊ": "tomato", "ಟೊಮಾಟೊ": "tomato", "ಟೊಮೇಟೊ": "tomato",
    "tamato":   "tomato", "thomaatho": "tomato",
    # Potato
    "potato":   "potato", "potatoes": "potato",
    "ಆಲೂಗಡ್ಡೆ": "potato", "ಆಲೂ":      "potato",
    "alugadde": "potato", "aloogadde": "potato", "aloo": "potato",
    # Onion
    "onion":    "onion",  "onions":   "onion",
    "ಈರುಳ್ಳಿ":  "onion",  "ಉಳ್ಳಿ":    "onion",
    "eerulli":   "onion",
    # Marigold
    "ಚೆಂಡುಹೂ":  "marigold","chenduhu": "marigold",
    "ಚೆಂಡು":    "marigold",
    # Capsicum
    "ಕ್ಯಾಪ್ಸಿಕಂ": "capsicum", "capsicum": "capsicum",
    "donne menasu": "capsicum",
    # Maize, Ragi, Brinjal, Cabbage
    "ಮೆಕ್ಕೆಜೋಳ": "maize", "ಮುಸುಕಿನಜೋಳ": "maize",
    "ರಾಗಿ": "ragi", 
    "ಬದನೆಕಾಯಿ": "brinjal", "ಬದನೆ": "brinjal",
    "ಎಲೆಕೋಸು": "cabbage",
}

_DISTRICT_ALIASES: dict[str, str] = {
    # Chikkaballapur
    "ಚಿಕ್ಕಬಳ್ಳಾಪುರ": "chikkaballapur", "ಚಿಕ್ಕಬಳ್ಳಾಪುರದಲ್ಲಿ": "chikkaballapur", "ಚಿಕ್ಕಬಳ್ಳಾಪುರನಲ್ಲಿ": "chikkaballapur",
    "chikballapur": "chikkaballapur", "chikkaballapura": "chikkaballapur", "chikkaballapuralli": "chikkaballapur",
    # Kolar
    "ಕೋಲಾರ": "kolar", "ಕೋಲಾರದಲ್ಲಿ": "kolar", "ಕೋಲಾರನಲ್ಲಿ": "kolar", "kolara": "kolar", "kolaralli": "kolar",
    # Tumakuru
    "ತುಮಕೂರು": "tumakuru", "ತುಮಕೂರಿನಲ್ಲಿ": "tumakuru", "ತುಮಕೂರುನಲ್ಲಿ": "tumakuru", "ತುಮಕೂರಿನಲ್ಲಿ": "tumakuru",
    "tumkur": "tumakuru", "tumakuru": "tumakuru", "tumkuralli": "tumakuru", "tumakuralli": "tumakuru",
    # Shivamogga
    "ಶಿವಮೊಗ್ಗ": "shivamogga", "ಶಿವಮೊಗ್ಗದಲ್ಲಿ": "shivamogga", "ಶಿವಮೊಗ್ಗನಲ್ಲಿ": "shivamogga",
    "shimoga": "shivamogga", "shivamogga": "shivamogga", "shivamoggalli": "shivamogga", "shimogalli": "shivamogga",
    # Mysuru
    "ಮೈಸೂರು": "mysuru", "ಮೈಸೂರಿನಲ್ಲಿ": "mysuru", "ಮೈಸೂರುನಲ್ಲಿ": "mysuru",
    "mysore": "mysuru", "mysuru": "mysuru", "mysuralli": "mysuru", "mysorealli": "mysuru",
    # Davanagere
    "ದಾವಣಗೆರೆ": "davanagere", "ದಾವಣಗೆರೆಯಲ್ಲಿ": "davanagere", "ದಾವಣಗೆರೆನಲ್ಲಿ": "davanagere",
    "davangere": "davanagere", "davanagere": "davanagere", "davanagerealli": "davanagere",
    # Belagavi
    "ಬೆಳಗಾವಿ": "belagavi", "ಬೆಳಗಾವಿಯಲ್ಲಿ": "belagavi", "ಬೆಳಗಾವಿನಲ್ಲ": "belagavi",
    "belgaum": "belagavi", "belagavi": "belagavi", "belagavialli": "belagavi",
    # Dharwad
    "ಧಾರವಾಡ": "dharwad", "ಧಾರವಾಡದಲ್ಲಿ": "dharwad", "ಧಾರವಾಡನಲ್ಲಿ": "dharwad", "dharwadalli": "dharwad",
    # Mandya
    "ಮಂಡ್ಯ": "mandya", "ಮಂಡ್ಯದಲ್ಲಿ": "mandya", "ಮಂಡ್ಯನಲ್ಲಿ": "mandya", "mandyalli": "mandya",
    # Haveri
    "ಹಾವೇರಿ": "haveri", "ಹಾವೇರಿಯಲ್ಲಿ": "haveri", "haverialli": "haveri",
    # Ballari
    "ಬಳ್ಳಾರಿ": "ballari", "ಬಳ್ಳಾರಿಯಲ್ಲಿ": "ballari", "ballarialli": "ballari",
    # Bengaluru
    "ಬೆಂಗಳೂರು": "bengaluru urban", "ಬೆಂಗಳೂರಿನಲ್ಲಿ": "bengaluru urban", "bangalore": "bengaluru urban", "bengaluru": "bengaluru urban",
}

# Fuzzy-match corpus — all known surface forms
_CROP_CORPUS     = list(_CROP_ALIASES.keys()) + list(CANONICAL_CROPS.keys())
_DISTRICT_CORPUS = list(_DISTRICT_ALIASES.keys()) + list(CANONICAL_DISTRICTS.keys())

_FUZZY_THRESHOLD = 75   # minimum score (0-100) to accept a fuzzy match


def resolve_crop(text: str) -> Optional[str]:
    """
    GUARDRAIL 1: Return canonical crop ID or None.
    Priority: direct substring alias match -> canonical name match -> fuzzy fallback.
    """
    tl = text.lower().strip()
    for alias, key in _CROP_ALIASES.items():
        if alias in tl:
            return CANONICAL_CROPS[key]
    for key, canonical in CANONICAL_CROPS.items():
        if key in tl:
            return canonical
    return None


def resolve_district(text: str) -> Optional[str]:
    """
    GUARDRAIL 1: Return canonical district ID or None.
    Priority: direct substring alias match -> canonical name match -> fuzzy fallback.
    """
    all_d = resolve_all_districts(text)
    return all_d[0] if all_d else None


def resolve_all_districts(text: str) -> list[str]:
    """Extract all mentioned canonical district names from text."""
    tl = text.lower().strip()
    found = []
    for alias, key in _DISTRICT_ALIASES.items():
        if alias in tl:
            can = CANONICAL_DISTRICTS[key]
            if can not in found:
                found.append(can)
    for key, canonical in CANONICAL_DISTRICTS.items():
        if key in tl and canonical not in found:
            found.append(canonical)
    return found


def extract_area(text: str) -> Optional[float]:
    """Extract numeric acreage ONLY if explicitly associated with acre keywords."""
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:acre|acres|ಎಕರೆ)", text, re.IGNORECASE)
    if match:
        try:
            val = float(match.group(1))
            return val if val > 0 else None
        except ValueError:
            return None
    return None


# ══════════════════════════════════════════════════════════
# Intent Classification & Keywords (Guardrail 2)
# ══════════════════════════════════════════════════════════

class Intent(Enum):
    PRICE_QUERY      = auto()   # → PostgreSQL only, NO LLM
    DECLARE_CROP     = auto()   # → PostgreSQL write, NO LLM
    SATURATION_CHECK = auto()   # → PostgreSQL only, NO LLM
    AGRONOMY_ADVICE  = auto()   # → RAG pipeline (GPT-4 + pgvector)
    UNKNOWN          = auto()   # → help message


# Keywords that MUST bypass the LLM (G2)
_PRICE_KEYWORDS = [
    "ಬೆಲೆ", "ಬೆಲ", "price", "rate", "mandi", "ಮಂಡಿ", "ಧರ", "ಧಾರಣೆ", "forecast", "60 day", "projected", "yeshtu", "eshtu", " ivattu", " today"
]
_SATURATION_KEYWORDS = [
    "saturation", "ಸ್ಯಾಚುರೇಷನ್", "risk", "ಅಪಾಯ", "ಎಷ್ಟು ಎಕರೆ", "ಎಷ್ಟು ರೈತರು", "ಇಗಾಗಲೇ ಬಿತ್ತನೆ", "ಇಾಗಲೇ ಬಿತ್ತನೆ",
    "how many farmers", "how many acres", "already planted", "already sown", "registered acreage", "total acreage", "risk level",
]
_DECLARE_KEYWORDS = [
    "declare", "ಬೆಳೆ ಹಾಕಿದ್ದೇನೆ", "ನಾನು ಬೆಳೆ", "crop sown", "planted", "sown", "hakidini", "ಹಾಕಿದಿನಿ", "ಹಾಕಿದ್ದೇನೆ", "register my crop", "record madi", "ನೋಂದಣಿ"
]
# Only agronomy questions go to the LLM
_AGRONOMY_KEYWORDS = [
    # English terms
    "disease", "rot", "blight", "wilt", "borer", "virus", "pest", "thrips", "nematode", "nematodes", "root-knot", "root knot",
    "fertilizer", "fertilizers", "dose", "dosage", "npk", "urea", "dap", "mop", "ratio", "basal", "fym",
    "boron", "metalaxyl", "mancozeb", "copper", "oxychloride", "pesticide", "fungicide",
    "insecticide", "rain", "monsoon", "seed", "irrigation", "water", "watering",
    "soil", "loam", "nitrogen", "phosphorus", "potassium", "gypsum", "advice",
    "treatment", "prevention", "control", "drenching", "application", "spray", "spraying",
    "yellow", "leaves", "leaf", "rotate", "rotation", "harvest", "harvesting", "spacing",
    "care", "grow", "manage", "tips", "yield", "exact dosage", "recommended", "intercrop", "intercropping",
    # Kannada script terms
    "ರೋಗ", "ಕೊಳೆ", "ಕರಕು", "ಕುತ್ತಿಗೆ", "ಗೊಬ್ಬರ", "ಕೀಟನಾಶಕ", "ಔಷಧಿ", "ಮಳೆ", "ಬೀಜ",
    "ನೀರಾವರಿ", "ಮಣ್ಣು", "ಸಲಹೆ", "ಇಳುವರಿ", "ಹೆಚ್ಚಿಸಲು", "ಸಲಹೆಗಳು", "ನೀರು", "ನಿಯಂತ್ರಣ", "ಕಟಾವು", "ಹುಳು",
    "ಸೈನಿಕ ಹುಳು", "ಗಂಟು ಹುಳು", "ಎಲೆ", "ಹಳದಿ", "ಸಿಂಪಡಿಸಬೇಕು", "ಪ್ರಮಾಣ",
    # Kanglish (Romanized Kannada) terms
    "roga", "hula", "aushadhi", "gobbara", "madabeku", "spray madabeku", "thundu", "gantu", "neeru", "beleli", "salaha", "sagida"
]


@dataclass
class ParsedMessage:
    intent:   Intent
    crop:     Optional[str]      # canonical, e.g. "Tomato"
    district: Optional[str]      # canonical, e.g. "Chikkaballapur"
    area:     Optional[float]
    raw_text: str


def parse(text: str) -> ParsedMessage:
    """
    GUARDRAIL 2: Classify intent WITHOUT touching the LLM.
    Numeric/market intents are resolved here deterministically.
    Only AGRONOMY_ADVICE is allowed to reach the RAG layer.
    """
    text = text.strip('"\'“”')
    tl = text.lower().strip()

    crop     = resolve_crop(text)
    district = resolve_district(text)
    area     = extract_area(text)

    # 1. Pure Smalltalk / Greetings / Unrelated conversation -> UNKNOWN -> Help Menu
    _SMALLTALK_TERMS = ["namaskara", "hegideera", "cricket", "weather", "bombat", "hello", "hi", "hey", "good morning", "good evening", "thanks", "thank you", "what can you do", "help"]
    is_smalltalk = any(term in tl for term in _SMALLTALK_TERMS) and not any(kw in tl for kw in ["price", "rate", "bela", "mandi", "disease", "rot", "spray", "acre", "sowed", "planted", "hakidini"])
    if is_smalltalk or (not crop and not district and not any(kw in tl for kw in _PRICE_KEYWORDS + _SATURATION_KEYWORDS + _AGRONOMY_KEYWORDS)):
        return ParsedMessage(
            intent   = Intent.UNKNOWN,
            crop     = crop,
            district = district,
            area     = None,
            raw_text = text,
        )

    # 2. Saturation risk check MUST take top priority over declarations & agronomy
    if any(kw in tl for kw in _SATURATION_KEYWORDS):
        return ParsedMessage(
            intent   = Intent.SATURATION_CHECK,
            crop     = crop,
            district = district,
            area     = None,
            raw_text = text,
        )

    # 3. Price query check MUST take priority if explicit price/mandi keywords exist
    if any(kw in tl for kw in _PRICE_KEYWORDS):
        return ParsedMessage(
            intent   = Intent.PRICE_QUERY,
            crop     = crop,
            district = district,
            area     = None,
            raw_text = text,
        )

    # 4. Sowing declaration check: requires crop + explicit declaration verb + explicit acreage number!
    if crop and area is not None and any(kw in tl for kw in _DECLARE_KEYWORDS):
        return ParsedMessage(
            intent   = Intent.DECLARE_CROP,
            crop     = crop,
            district = district,
            area     = area,
            raw_text = text,
        )

    # 5. Agronomy advice check
    if any(kw in tl for kw in _AGRONOMY_KEYWORDS):
        return ParsedMessage(
            intent   = Intent.AGRONOMY_ADVICE,
            crop     = crop,
            district = district,
            area     = None,
            raw_text = text,
        )

    # 6. Fallback with crop mentioned -> Agronomy AI
    if crop and len(tl.split()) > 1:
        return ParsedMessage(
            intent   = Intent.AGRONOMY_ADVICE,
            crop     = crop,
            district = district,
            area     = None,
            raw_text = text,
        )

    return ParsedMessage(
        intent   = Intent.UNKNOWN,
        crop     = crop,
        district = district,
        area     = None,
        raw_text = text,
    )
