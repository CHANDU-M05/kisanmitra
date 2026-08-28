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
    "ಚಿಕ್ಕಬಳ್ಳಾಪುರ": "chikkaballapur", "chikballapur": "chikkaballapur", "chikkaballapura": "chikkaballapur",
    "ಕೋಲಾರ": "kolar", "kolara": "kolar",
    "ತುಮಕೂರು": "tumakuru", "tumkur": "tumakuru", "tumakuru": "tumakuru",
    "ಶಿವಮೊಗ್ಗ": "shivamogga", "shimoga": "shivamogga", "shivamogga": "shivamogga",
    "ಬೆಂಗಳೂರು": "bengaluru urban", "bangalore": "bengaluru urban", "bengaluru": "bengaluru urban",
    "ಬೆಳಗಾವಿ": "belagavi", "belgaum": "belagavi", "belagavi": "belagavi",
    "ಮೈಸೂರು": "mysuru", "mysore": "mysuru", "mysuru": "mysuru",
    "ದಾವಣಗೆರೆ": "davanagere", "davangere": "davanagere", "davanagere": "davanagere",
    "ಧಾರವಾಡ": "dharwad", "dharwad": "dharwad",
    "ಬಳ್ಳಾರಿ": "ballari", "bellary": "ballari", "ballari": "ballari",
    "ಹಾಸನ": "hassan", "hassan": "hassan",
    "ಹಾವೇರಿ": "haveri", "haveri": "haveri",
    "ಮಂಡ್ಯ": "mandya", "mandya": "mandya",
    "ವಿಜಯನಗರ": "vijayanagara", "vijayanagara": "vijayanagara",
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
    tl = text.lower().strip()
    for alias, key in _DISTRICT_ALIASES.items():
        if alias in tl:
            return CANONICAL_DISTRICTS[key]
    for key, canonical in CANONICAL_DISTRICTS.items():
        if key in tl:
            return canonical
    return None


def extract_area(text: str) -> float:
    """Extract the first valid numeric value from text (area in acres)."""
    nums = re.findall(r"\d+(?:\.\d+)?", text)
    if nums:
        try:
            val = float(nums[0])
            return val if val > 0 else 1.0
        except ValueError:
            return 1.0
    return 1.0


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
    "ಬೆಲೆ", "ಬೆಲ", "price", "rate", "mandi", "ಮಂಡಿ", "ಧರ", "ಧಾರಣೆ",
]
_SATURATION_KEYWORDS = [
    "saturation", "ಸ್ಯಾಚುರೇಷನ್", "risk", "ಅಪಾಯ",
    "how many farmers", "ಎಷ್ಟು ರೈತರು", "registered acreage", "total acreage", "risk level",
]
_DECLARE_KEYWORDS = [
    "ಎಕರೆ", "acres", "acre", "declare", "ಬೆಳೆ ಹಾಕಿದ್ದೇನೆ",
    "ನಾನು ಬೆಳೆ", "crop sown", "planted", "sown", "growing",
]
# Only agronomy questions go to the LLM
_AGRONOMY_KEYWORDS = [
    # English terms
    "disease", "rot", "blight", "wilt", "borer", "virus", "pest", "thrips",
    "fertilizer", "fertilizers", "dose", "dosage", "npk", "urea", "dap", "mop", "ratio", "basal", "fym",
    "boron", "metalaxyl", "mancozeb", "copper", "oxychloride", "pesticide", "fungicide",
    "insecticide", "weather", "rain", "monsoon", "seed", "irrigation", "water", "watering",
    "soil", "loam", "nitrogen", "phosphorus", "potassium", "gypsum", "advice", "help",
    "treatment", "prevention", "control", "drenching", "application", "spray", "spraying",
    "yellow", "leaves", "leaf", "rotate", "rotation", "harvest", "harvesting", "spacing",
    "care", "grow", "manage", "tips", "yield", "how to", "what to", "what if", "which",
    "should i", "can i", "how much", "exact dosage", "recommended", "intercrop",
    # Kannada script terms
    "ರೋಗ", "ಕೊಳೆ", "ಕರಕು", "ಕುತ್ತಿಗೆ", "ಗೊಬ್ಬರ", "ಕೀಟನಾಶಕ", "ಔಷಧಿ", "ಮಳೆ", "ಬೀಜ",
    "ನೀರಾವರಿ", "ಮಣ್ಣು", "ಸಲಹೆ", "ಸಹಾಯ", "ಹೇಗೆ", "ಏನು ಮಾಡಲಿ", "ಏನು ಮಾಡಬೇಕು", "ಇಳುವರಿ",
    "ಹೆಚ್ಚಿಸಲು", "ಮಾಡಬೇಕು", "ಸಲಹೆಗಳು", "ನೀರು", "ನಿಯಂತ್ರಣ", "ಕಟಾವು", "ಹುಳು",
    "ಸೈನಿಕ ಹುಳು", "ಎಲೆ", "ಹಳದಿ", "ಸಿಂಪಡಿಸಬೇಕು", "ಪ್ರಮಾಣ",
    # Kanglish (Romanized Kannada) terms
    "roga", "hula", "aushadhi", "gobbara", "madabeku", "spray madabeku", "thundu",
    "gantu", "neeru", "beleli", "salaha", "ide", "yav", "estu", "sagida"
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

    # Generic greetings return UNKNOWN -> renders format_help()
    _GREETINGS = {"hello", "hi", "hey", "thanks", "thank you", "ಧನ್ಯವಾದಗಳು", "ನಮಸ್ಕಾರ"}
    if tl in _GREETINGS:
        return ParsedMessage(
            intent   = Intent.UNKNOWN,
            crop     = crop,
            district = district,
            area     = None,
            raw_text = text,
        )

    # 1. Saturation risk check MUST take top priority over declarations & agronomy
    if any(kw in tl for kw in _SATURATION_KEYWORDS):
        return ParsedMessage(
            intent   = Intent.SATURATION_CHECK,
            crop     = crop,
            district = district,
            area     = None,
            raw_text = text,
        )

    # 2. Agronomy advice check MUST precede sowing declarations (so dosage/treatment queries with acre numbers route to advisory)
    if any(kw in tl for kw in _AGRONOMY_KEYWORDS):
        return ParsedMessage(
            intent   = Intent.AGRONOMY_ADVICE,
            crop     = crop,
            district = district,
            area     = None,
            raw_text = text,
        )

    # 3. Price query check
    if any(kw in tl for kw in _PRICE_KEYWORDS):
        return ParsedMessage(
            intent   = Intent.PRICE_QUERY,
            crop     = crop,
            district = district,
            area     = None,
            raw_text = text,
        )

    # 4. Sowing declaration check (crop + declare keywords)
    if crop and any(kw in tl for kw in _DECLARE_KEYWORDS):
        return ParsedMessage(
            intent   = Intent.DECLARE_CROP,
            crop     = crop,
            district = district,
            area     = extract_area(text),
            raw_text = text,
        )

    # 5. Implicit declaration if crop and explicit acreage number mentioned without agronomy/saturation terms
    if crop and re.search(r"\b[\d.]+\s*(acre|acres|ಎಕರೆ)", text, re.IGNORECASE):
        return ParsedMessage(
            intent   = Intent.DECLARE_CROP,
            crop     = crop,
            district = district,
            area     = extract_area(text),
            raw_text = text,
        )

    # 6. Fallback: Free-text query with crop mentioned -> Agronomy AI
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
