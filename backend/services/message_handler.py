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
    "ಟೊಮ್ಯಾಟೊ":  "tomato", "ಟೊಮೆಟೊ":   "tomato",
    "ಟೊಮೇಟೊ":   "tomato", "ತಕ್ಕಾಳಿ":  "tomato",
    "tameta":    "tomato", "tamato":   "tomato",
    # Potato
    "ಆಲೂಗಡ್ಡೆ": "potato", "ಆಲೂ":      "potato",
    "alu":       "potato", "aloogadde":"potato",
    # Onion
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
    Matches exact crop tokens or alias keys against word boundaries in text.
    """
    tl = text.lower().strip()
    clean_text = re.sub(r"[^\w\s]", " ", tl)
    words = clean_text.split()

    # 1. Exact canonical name match
    for w in words:
        if w in CANONICAL_CROPS:
            return CANONICAL_CROPS[w]

    # 2. Direct alias lookup (word match or explicit multi-word alias match)
    for alias, key in _CROP_ALIASES.items():
        if alias in words or (len(alias.split()) > 1 and alias in tl):
            return CANONICAL_CROPS[key]

    # 3. High-confidence fuzzy match (threshold 88) on individual words (>= 4 chars)
    for token in words:
        if len(token) >= 4:
            match, score = fuzz_process.extractOne(token, _CROP_CORPUS) or (None, 0)
            if score >= 88 and match:
                key = _CROP_ALIASES.get(match, match)
                if key in CANONICAL_CROPS:
                    logger.debug("[FUZZY CROP] '%s' → '%s' (score=%d)", token, key, score)
                    return CANONICAL_CROPS[key]

    return None


def resolve_district(text: str) -> Optional[str]:
    """
    GUARDRAIL 1: Return canonical district ID or None.
    Matches exact district tokens or alias keys against word boundaries in text.
    """
    tl = text.lower().strip()
    clean_text = re.sub(r"[^\w\s]", " ", tl)
    words = clean_text.split()

    # 1. Direct alias lookup or canonical name match
    for alias, key in _DISTRICT_ALIASES.items():
        if alias in words or alias in tl:
            return CANONICAL_DISTRICTS[key]

    for w in words:
        if w in CANONICAL_DISTRICTS:
            return CANONICAL_DISTRICTS[w]

    # 2. High-confidence fuzzy match (threshold 88) on individual words (>= 5 chars)
    for token in words:
        if len(token) >= 5:
            match, score = fuzz_process.extractOne(token, _DISTRICT_CORPUS) or (None, 0)
            if score >= 88 and match:
                key = _DISTRICT_ALIASES.get(match, match)
                if key in CANONICAL_DISTRICTS:
                    logger.debug("[FUZZY DISTRICT] '%s' → '%s' (score=%d)", token, key, score)
                    return CANONICAL_DISTRICTS[key]

    return None


def extract_area(text: str) -> float:
    """Extract the first numeric value from text (area in acres)."""
    nums = re.findall(r"[\d.]+", text)
    return float(nums[0]) if nums else 1.0


# ══════════════════════════════════════════════════════════
# GUARDRAIL 2: Intent classification
# ══════════════════════════════════════════════════════════

class Intent(Enum):
    PRICE_QUERY      = auto()   # → PostgreSQL only, NO LLM
    DECLARE_CROP     = auto()   # → PostgreSQL write, NO LLM
    SATURATION_CHECK = auto()   # → PostgreSQL only, NO LLM
    AGRONOMY_ADVICE  = auto()   # → RAG pipeline (GPT-4 + pgvector)
    UNKNOWN          = auto()   # → help message


# Keywords that MUST bypass the LLM (G2)
_PRICE_KEYWORDS = [
    "ಬೆಲೆ", "ಬೆಲ", "price", "rate", "mandi", "ಮಂಡಿ", "ಧರ",
]
_DECLARE_KEYWORDS = [
    "ಎಕರೆ", "acres", "acre", "declare", "ಬೆಳೆ ಹಾಕಿದ್ದೇನೆ",
    "ನಾನು ಬೆಳೆ", "crop sown",
]
_SATURATION_KEYWORDS = [
    "saturation", "ಸ್ಯಾಚುರೇಷನ್", "risk", "ಅಪಾಯ",
    "how many farmers", "ಎಷ್ಟು ರೈತರು",
]
# Only agronomy questions go to the LLM
_AGRONOMY_KEYWORDS = [
    # English terms
    "disease", "rot", "blight", "wilt", "borer", "virus", "pest",
    "fertilizer", "fertilizers", "dose", "dosage", "npk", "urea", "dap", "mop",
    "boron", "metalaxyl", "mancozeb", "copper", "oxychloride", "pesticide", "fungicide",
    "insecticide", "weather", "rain", "monsoon", "seed", "irrigation", "water", "watering",
    "soil", "loam", "nitrogen", "phosphorus", "potassium", "gypsum", "advice", "help",
    "treatment", "prevention", "control", "drenching", "application", "spray", "spraying",
    "yellow", "leaves", "leaf", "rotate", "rotation", "harvest", "harvesting", "spacing",
    "care", "grow", "manage", "tips", "yield", "how to", "what to", "what if", "which",
    "should i", "can i", "how much", "how many", "exact dosage",
    # Kannada script terms
    "ರೋಗ", "ಕೊಳೆ", "ಕರಕು", "ಕುತ್ತಿಗೆ", "ಗೊಬ್ಬರ", "ಕೀಟನಾಶಕ", "ಔಷಧಿ", "ಮಳೆ", "ಬೀಜ",
    "ನೀರಾವರಿ", "ಮಣ್ಣು", "ಸಲಹೆ", "ಸಹಾಯ", "ಹೇಗೆ", "ಏನು ಮಾಡಲಿ", "ಏನು ಮಾಡಬೇಕು", "ಇಳುವರಿ",
    "ಹೆಚ್ಚಿಸಲು", "ಮಾಡಬೇಕು", "ಸಲಹೆಗಳು", "ನೀರು", "ನಿಯಂತ್ರಣ", "ಕಟಾವು", "ಬೆಳೆ", "ಹುಳು",
    "ಸೈನಿಕ ಹುಳು", "ಎಲೆ", "ಹಳದಿ", "ಸಿಂಪಡಿಸಬೇಕು", "ಪ್ರಮಾಣ",
    # Kanglish (Romanized Kannada) terms
    "roga", "hula", "aushadhi", "gobbara", "madabeku", "spray madabeku", "thundu",
    "gantu", "neeru", "beleli", "salaha", "ide", "yav", "estu"
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
    # Clean up quotes and explanatory notes in parentheses
    text = text.strip('"\'“”')
    tl = text.lower()

    crop     = resolve_crop(text)
    district = resolve_district(text)

    # 1. Agronomy check MUST come first so questions like
    # "How much fertilizer for 2 acres of tomato" route to Agronomy AI, NOT declaration.
    if any(kw in tl for kw in _AGRONOMY_KEYWORDS):
        return ParsedMessage(
            intent   = Intent.AGRONOMY_ADVICE,
            crop     = crop,
            district = district,
            area     = None,
            raw_text = text,
        )

    # 2. Sowing declaration check
    if crop and any(kw in tl for kw in _DECLARE_KEYWORDS):
        return ParsedMessage(
            intent   = Intent.DECLARE_CROP,
            crop     = crop,
            district = district,
            area     = extract_area(text),
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

    # 4. Saturation risk check
    if any(kw in tl for kw in _SATURATION_KEYWORDS):
        return ParsedMessage(
            intent   = Intent.SATURATION_CHECK,
            crop     = crop,
            district = district,
            area     = None,
            raw_text = text,
        )

    # 5. Implicit declaration if crop and number are mentioned without explicit intent
    if crop and re.search(r"[\d.]+\s*(acre|acres|ಎಕರೆ)?", text, re.IGNORECASE):
        return ParsedMessage(
            intent   = Intent.DECLARE_CROP,
            crop     = crop,
            district = district,
            area     = extract_area(text),
            raw_text = text,
        )

    # 6. Fallback free-text queries > 2 words route to Agronomy AI
    if len(tl.split()) > 2:
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
