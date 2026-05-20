"""
api/services/message_handler.py — GUARDRAILS 1 & 2

GUARDRAIL 1 — FUZZY MATCHING
    Farmer input is never evaluated with strict equality.
    All crop and district names are resolved to canonical IDs via:
      1. A predefined alias dictionary (handles known Kannada variants)
      2. thefuzz token_set_ratio as the fallback (handles typos)

GUARDRAIL 2 — DETERMINISTIC ROUTING
    Intent routing is strictly separated:
      • PRICE / SATURATION  →  PostgreSQL query + f-string template (NO LLM)
      • AGRONOMY / ADVISORY →  RAG pipeline (GPT-4 + pgvector)
    The LLM is never invoked for numeric or market-data intents.
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
}

CANONICAL_DISTRICTS: dict[str, str] = {
    "chikkaballapur": "Chikkaballapur",
    "kolar":          "Kolar",
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
}

_DISTRICT_ALIASES: dict[str, str] = {
    "ಚಿಕ್ಕಬಳ್ಳಾಪುರ": "chikkaballapur",
    "chikballapur":   "chikkaballapur",
    "chikkaballapura":"chikkaballapur",
    "ಕೋಲಾರ":          "kolar",
    "kolara":         "kolar",
}

# Fuzzy-match corpus — all known surface forms
_CROP_CORPUS     = list(_CROP_ALIASES.keys()) + list(CANONICAL_CROPS.keys())
_DISTRICT_CORPUS = list(_DISTRICT_ALIASES.keys()) + list(CANONICAL_DISTRICTS.keys())

_FUZZY_THRESHOLD = 75   # minimum score (0-100) to accept a fuzzy match


def resolve_crop(text: str) -> Optional[str]:
    """
    GUARDRAIL 1: Return canonical crop ID or None.
    Priority: alias dict → fuzzy match → None.
    """
    tl = text.lower().strip()

    # 1. Direct alias lookup
    for alias, key in _CROP_ALIASES.items():
        if alias in tl:
            return CANONICAL_CROPS[key]

    # 2. Fuzzy fallback on individual tokens
    for token in tl.split():
        match, score = fuzz_process.extractOne(token, _CROP_CORPUS) or (None, 0)
        if score >= _FUZZY_THRESHOLD and match:
            key = _CROP_ALIASES.get(match, match)
            if key in CANONICAL_CROPS:
                logger.debug("[FUZZY CROP] '%s' → '%s' (score=%d)", token, key, score)
                return CANONICAL_CROPS[key]

    return None


def resolve_district(text: str) -> Optional[str]:
    """
    GUARDRAIL 1: Return canonical district ID or None.
    Defaults to Chikkaballapur if no district is found in text.
    """
    tl = text.lower().strip()

    for alias, key in _DISTRICT_ALIASES.items():
        if alias in tl:
            return CANONICAL_DISTRICTS[key]

    for token in tl.split():
        match, score = fuzz_process.extractOne(token, _DISTRICT_CORPUS) or (None, 0)
        if score >= _FUZZY_THRESHOLD and match:
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
    "disease", "ರೋಗ", "fertilizer", "ಗೊಬ್ಬರ", "pesticide", "ಕೀಟನಾಶಕ",
    "weather", "ಮಳೆ", "seed", "ಬೀಜ", "irrigation", "ನೀರಾವರಿ",
    "soil", "ಮಣ್ಣು", "advice", "ಸಲಹೆ", "help", "ಸಹಾಯ",
    "how to", "ಹೇಗೆ", "what to", "ಏನು ಮಾಡಲಿ",
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
    tl = text.lower()

    crop     = resolve_crop(text)
    district = resolve_district(text)

    # Priority order matters — declare check before price check
    # so "2 acres tomato" is not confused with a price query.
    if crop and any(kw in tl for kw in _DECLARE_KEYWORDS):
        return ParsedMessage(
            intent   = Intent.DECLARE_CROP,
            crop     = crop,
            district = district,
            area     = extract_area(text),
            raw_text = text,
        )

    if any(kw in tl for kw in _PRICE_KEYWORDS):
        return ParsedMessage(
            intent   = Intent.PRICE_QUERY,
            crop     = crop,
            district = district,
            area     = None,
            raw_text = text,
        )

    if any(kw in tl for kw in _SATURATION_KEYWORDS):
        return ParsedMessage(
            intent   = Intent.SATURATION_CHECK,
            crop     = crop,
            district = district,
            area     = None,
            raw_text = text,
        )

    # Crop mentioned without explicit declare keyword →
    # treat as implicit declaration if area number present
    if crop and re.search(r"[\d.]+", text):
        return ParsedMessage(
            intent   = Intent.DECLARE_CROP,
            crop     = crop,
            district = district,
            area     = extract_area(text),
            raw_text = text,
        )

    if any(kw in tl for kw in _AGRONOMY_KEYWORDS):
        return ParsedMessage(
            intent   = Intent.AGRONOMY_ADVICE,   # ← ONLY path to LLM
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
