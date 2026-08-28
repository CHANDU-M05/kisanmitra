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
    "groundnut": "Groundnut",
}

CANONICAL_DISTRICTS: dict[str, str] = {
    "bagalkote": "Bagalkote", "ballari": "Ballari", "belagavi": "Belagavi",
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

# ── GUARDRAIL 1: Alias tables (canonical Kannada variants & alternate spellings) ─
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
    # Maize, Ragi, Brinjal, Cabbage, Groundnut
    "ಮೆಕ್ಕೆಜೋಳ": "maize", "ಮುಸುಕಿನಜೋಳ": "maize",
    "ರಾಗಿ": "ragi", 
    "ಬದನೆಕಾಯಿ": "brinjal", "ಬದನೆ": "brinjal",
    "ಎಲೆಕೋಸು": "cabbage",
    "groundnut": "groundnut", "groundnuts": "groundnut", "peanut": "groundnut", "peanuts": "groundnut",
    "ಕಡಲೆಕಾಯಿ": "groundnut", "ನೆಲಗಡಲೆ": "groundnut", "kadalekayi": "groundnut", "nelagadale": "groundnut",
}

_DISTRICT_ALIASES: dict[str, str] = {
    # Bagalkote
    "bagalkot": "bagalkote", "bagalkote": "bagalkote", "ಬಾಗಲಕೋಟೆ": "bagalkote", "ಬಾಗಲಕೋಟೆಯಲ್ಲಿ": "bagalkote", "bagalkotalli": "bagalkote",
    # Ballari
    "ballari": "ballari", "bellary": "ballari", "ಬಳ್ಳಾರಿ": "ballari", "ಬಳ್ಳಾರಿಯಲ್ಲಿ": "ballari", "ballarialli": "ballari", "bellaryalli": "ballari",
    # Belagavi
    "belagavi": "belagavi", "belgaum": "belagavi", "ಬೆಳಗಾವಿ": "belagavi", "ಬೆಳಗಾವಿಯಲ್ಲಿ": "belagavi", "belagavialli": "belagavi", "belgaumalli": "belagavi",
    # Bengaluru Rural
    "bengaluru rural": "bengaluru rural", "bangalore rural": "bengaluru rural", "ಬೆಂಗಳೂರು ಗ್ರಾಮಾಂತರ": "bengaluru rural",
    # Bengaluru Urban
    "bengaluru urban": "bengaluru urban", "bangalore urban": "bengaluru urban", "bangalore": "bengaluru urban", "bengaluru": "bengaluru urban",
    "ಬೆಂಗಳೂರು": "bengaluru urban", "ಬೆಂಗಳೂರಿನಲ್ಲಿ": "bengaluru urban", "bengalurualli": "bengaluru urban", "bangalorealli": "bengaluru urban",
    # Bidar
    "bidar": "bidar", "ಬೀದರ್": "bidar", "ಬೀದರ್‌ನಲ್ಲಿ": "bidar", "bidaralli": "bidar",
    # Chamarajanagar
    "chamarajanagar": "chamarajanagar", "chamrajnagar": "chamarajanagar", "chamarajanagara": "chamarajanagar",
    "ಚಾಮರಾಜನಗರ": "chamarajanagar", "ಚಾಮರಾಜನಗರದಲ್ಲಿ": "chamarajanagar", "chamarajanagaralli": "chamarajanagar",
    # Chikkaballapur
    "chikkaballapur": "chikkaballapur", "chikballapur": "chikkaballapur", "chikkaballapura": "chikkaballapur", "chikaballapur": "chikkaballapur",
    "ಚಿಕ್ಕಬಳ್ಳಾಪುರ": "chikkaballapur", "ಚಿಕ್ಕಬಳ್ಳಾಪುರದಲ್ಲಿ": "chikkaballapur", "chikkaballapuralli": "chikkaballapur", "chikballapuralli": "chikkaballapur",
    # Chikkamagaluru
    "chikkamagaluru": "chikkamagaluru", "chikmagalur": "chikkamagaluru", "chickmagalur": "chikkamagaluru",
    "ಚಿಕ್ಕಮಗಳೂರು": "chikkamagaluru", "ಚಿಕ್ಕಮಗಳೂರಿನಲ್ಲಿ": "chikkamagaluru", "chikkamagalurualli": "chikkamagaluru",
    # Chitradurga
    "chitradurga": "chitradurga", "chitradurg": "chitradurga", "ಚಿತ್ರದುರ್ಗ": "chitradurga", "ಚಿತ್ರದುರ್ಗದಲ್ಲಿ": "chitradurga", "chitradurgaalli": "chitradurga",
    # Dakshina Kannada
    "dakshina kannada": "dakshina kannada", "south canara": "dakshina kannada", "mangalore": "dakshina kannada", "mangaluru": "dakshina kannada",
    "ದಕ್ಷಿಣ ಕನ್ನಡ": "dakshina kannada", "ಮಂಗಳೂರು": "dakshina kannada", "mangalurualli": "dakshina kannada",
    # Davanagere
    "davanagere": "davanagere", "davangere": "davanagere", "ದಾವಣಗೆರೆ": "davanagere", "ದಾವಣಗೆರೆಯಲ್ಲಿ": "davanagere", "davanagerealli": "davanagere", "davangerealli": "davanagere",
    # Dharwad
    "dharwad": "dharwad", "dharwar": "dharwad", "ಧಾರವಾಡ": "dharwad", "ಧಾರವಾಡದಲ್ಲಿ": "dharwad", "dharwadalli": "dharwad",
    # Gadag
    "gadag": "gadag", "ಗದುಗ": "gadag", "ಗದಗ": "gadag", "ಗದಗದಲ್ಲಿ": "gadag", "gadagalli": "gadag",
    # Hassan
    "hassan": "hassan", "ಹಾಸನ": "hassan", "ಹಾಸನದಲ್ಲಿ": "hassan", "hassanalli": "hassan",
    # Haveri
    "haveri": "haveri", "haverii": "haveri", "ಹಾವೇರಿ": "haveri", "ಹಾವೇರಿಯಲ್ಲಿ": "haveri", "haverialli": "haveri",
    # Kalaburagi
    "kalaburagi": "kalaburagi", "gulbarga": "kalaburagi", "ಕಲಬುರಗಿ": "kalaburagi", "ಕಲಬುರಗಿಯಲ್ಲಿ": "kalaburagi", "kalaburagialli": "kalaburagi", "gulbargaalli": "kalaburagi",
    # Kodagu
    "kodagu": "kodagu", "coorg": "kodagu", "mercara": "kodagu", "ಕೊಡಗು": "kodagu", "ಕೊಡಗಿನಲ್ಲಿ": "kodagu", "kodagualli": "kodagu", "coorgalli": "kodagu",
    # Kolar
    "kolar": "kolar", "kolara": "kolar", "ಕೋಲಾರ": "kolar", "ಕೋಲಾರದಲ್ಲಿ": "kolar", "kolaralli": "kolar",
    # Koppal
    "koppal": "koppal", "ಕೊಪ್ಪಳ": "koppal", "ಕೊಪ್ಪಳದಲ್ಲಿ": "koppal", "koppalalli": "koppal",
    # Mandya
    "mandya": "mandya", "ಮಂಡ್ಯ": "mandya", "ಮಂಡ್ಯದಲ್ಲಿ": "mandya", "mandyalli": "mandya",
    # Mysuru
    "mysuru": "mysuru", "mysore": "mysuru", "ಮೈಸೂರು": "mysuru", "ಮೈಸೂರಿನಲ್ಲಿ": "mysuru", "mysuralli": "mysuru", "mysorealli": "mysuru",
    # Raichur
    "raichur": "raichur", "ರಾಯಚೂರು": "raichur", "ರಾಯಚೂರಿನಲ್ಲಿ": "raichur", "raichuralli": "raichur",
    # Ramanagara
    "ramanagara": "ramanagara", "ramanagaram": "ramanagara", "ರಾಮನಗರ": "ramanagara", "ರಾಮನಗರದಲ್ಲಿ": "ramanagara", "ramanagaraalli": "ramanagara",
    # Shivamogga
    "shivamogga": "shivamogga", "shimoga": "shivamogga", "ಶಿವಮೊಗ್ಗ": "shivamogga", "ಶಿವಮೊಗ್ಗದಲ್ಲಿ": "shivamogga", "shivamoggalli": "shivamogga", "shimogalli": "shivamogga",
    # Tumakuru
    "tumakuru": "tumakuru", "tumkur": "tumakuru", "ತುಮಕೂರು": "tumakuru", "ತುಮಕೂರಿನಲ್ಲಿ": "tumakuru", "tumakuralli": "tumakuru", "tumkuralli": "tumakuru",
    # Udupi
    "udupi": "udupi", "udipi": "udupi", "ಉಡುಪಿ": "udupi", "ಉಡುಪಿಯಲ್ಲಿ": "udupi", "udupialli": "udupi",
    # Uttara Kannada
    "uttara kannada": "uttara kannada", "north canara": "uttara kannada", "karwar": "uttara kannada", "ಉತ್ತರ ಕನ್ನಡ": "uttara kannada", "ಕಾರವಾರ": "uttara kannada", "karwaralli": "uttara kannada",
    # Vijayanagara
    "vijayanagara": "vijayanagara", "hospet": "vijayanagara", "hosapete": "vijayanagara", "ವಿಜಯನಗರ": "vijayanagara", "ಹೊಸಪೇಟೆ": "vijayanagara", "vijayanagaraalli": "vijayanagara",
    # Vijayapura
    "vijayapura": "vijayapura", "bijapur": "vijayapura", "ವಿಜಯಪುರ": "vijayapura", "ಬಿಜಾಪುರ": "vijayapura", "ವಿಜಯಪುರದಲ್ಲಿ": "vijayapura", "bijapuralli": "vijayapura", "vijayapuraalli": "vijayapura",
    # Yadgir
    "yadgir": "yadgir", "yadgiri": "yadgir", "ಯಾದಗಿರಿ": "yadgir", "ಯಾದಗಿರಿಯಲ್ಲಿ": "yadgir", "yadgiralli": "yadgir",
}

# Fuzzy-match corpus — all known surface forms
_CROP_CORPUS     = list(_CROP_ALIASES.keys()) + list(CANONICAL_CROPS.keys())
_DISTRICT_CORPUS = list(_DISTRICT_ALIASES.keys()) + list(CANONICAL_DISTRICTS.keys())

_FUZZY_THRESHOLD = 75   # minimum score (0-100) to accept a fuzzy match


def resolve_crop(text: str) -> Optional[str]:
    """
    GUARDRAIL 1: Return canonical crop ID or None.
    Priority: main cash crop position -> word boundary alias match.
    Uses \b word boundary for ASCII terms (e.g. 'ragi' in 'kalaburagi') and
    substring matching for Unicode/Kannada script terms.
    """
    tl = text.lower().strip()
    
    # Primary cash crops take precedence over trap crops (e.g. Marigold)
    PRIMARY_CROPS = ["Tomato", "Potato", "Onion", "Maize", "Groundnut", "Capsicum", "Cabbage", "Brinjal"]
    
    # Check if a primary cash crop is present
    for main_crop in PRIMARY_CROPS:
        if re.search(r"\b" + re.escape(main_crop.lower()) + r"\b", tl):
            return main_crop
            
    earliest_idx = len(tl) + 1
    matched_crop = None

    for alias, key in _CROP_ALIASES.items():
        is_ascii = alias.isascii()
        pattern = r"\b" + re.escape(alias.lower()) + r"\b" if is_ascii else re.escape(alias.lower())
        match = re.search(pattern, tl)
        if match:
            pos = match.start()
            if pos < earliest_idx:
                earliest_idx = pos
                matched_crop = CANONICAL_CROPS[key]

    for key, canonical in CANONICAL_CROPS.items():
        is_ascii = key.isascii()
        pattern = r"\b" + re.escape(key.lower()) + r"\b" if is_ascii else re.escape(key.lower())
        match = re.search(pattern, tl)
        if match:
            pos = match.start()
            if pos < earliest_idx:
                earliest_idx = pos
                matched_crop = canonical

    return matched_crop


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
    "ಬೆಲೆ", "ಬೆಲ", "price", "rate", "mandi", "ಮಂಡಿ", "ಧರ", "ಧಾರಣೆ", "forecast", "60 day", "60-day", "projected"
]
_SATURATION_KEYWORDS = [
    "saturation", "ಸ್ಯಾಚುರೇಷನ್", "risk", "ಅಪಾಯ", "ಎಷ್ಟು ಎಕರೆ", "ಎಷ್ಟು ರೈತರು", "ಇಗಾಗಲೇ ಬಿತ್ತನೆ", "ಇಾಗಲೇ ಬಿತ್ತನೆ",
    "how many farmers", "how many acres", "already planted", "already sown", "registered acreage", "total acreage", "risk level",
    "across all farmers", "registered in", "how many total acres", "this season", "how many total farmers", "farmers planted", "total farmers"
]
_DECLARE_KEYWORDS = [
    "declare", "sowed", "sown", "planted", "hakidini", "ಹಾಕಿದಿನಿ", "ಹಾಕಿದ್ದೇನೆ",
    "ಬೆಳೆ ಹಾಕಿದ್ದೇನೆ", "ನಾನು ಬೆಳೆ", "register my crop", "record entry", "record in database",
    "crop sown", "planted crop"
]
# Only agronomy questions go to the LLM
_AGRONOMY_KEYWORDS = [
    # English terms
    "disease", "rot", "blight", "wilt", "borer", "virus", "pest", "thrips", "nematode", "nematodes", "root-knot", "root knot",
    "fertilizer", "fertilizers", "dose", "dosage", "npk", "urea", "dap", "mop", "ratio", "basal", "fym",
    "boron", "metalaxyl", "mancozeb", "copper", "oxychloride", "pesticide", "fungicide",
    "insecticide", "monsoon", "seed", "irrigation", "water", "watering",
    "soil", "loam", "nitrogen", "phosphorus", "potassium", "gypsum", "advice",
    "treatment", "prevention", "control", "drenching", "application", "spray", "spraying",
    "yellow", "leaves", "leaf", "rotate", "rotation", "harvest", "harvesting", "spacing",
    "care", "grow", "manage", "tips", "yield", "exact dosage", "recommended", "intercrop", "intercropping",
    # Kannada script terms
    "ರೋಗ", "ಕೊಳೆ", "ಕರಕು", "ಕುತ್ತಿಗೆ", "ಗೊಬ್ಬರ", "ಕೀಟನಾಶಕ", "ಔಷಧಿ", "ಬೀಜ",
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

    # 1. Non-agronomic / General / Travel / Geography / Weather / Tourism / Smalltalk -> UNKNOWN -> Help Menu
    _NON_AGRI_TERMS = [
        "umbrella", "geography", "history", "travel", "coffee", "restaurant", "hotel", "cricket", "rain", "weather",
        "tourist", "tourist places", "sightseeing", "visit", "places to visit", "places",
        "namaskara", "hegideera", "bombat", "hello", "hi", "hey", "good morning", "good evening",
        "thanks", "thank you", "what can you do", "helping farmers", "how is kisanmitra", "about kisanmitra", "who are you"
    ]
    has_non_agri = any(term in tl for term in _NON_AGRI_TERMS)
    has_agri_kw = any(kw in tl for kw in _PRICE_KEYWORDS + _SATURATION_KEYWORDS + _DECLARE_KEYWORDS + _AGRONOMY_KEYWORDS)
    
    # Critical Rule: If text has non-agri terms or lacks both crop AND agronomy keywords, ALWAYS return UNKNOWN!
    if (has_non_agri and not crop) or not (crop or has_agri_kw):
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

    # 3. Sowing declaration check: requires crop + explicit acreage number + explicit declaration verb!
    if crop and area is not None and any(kw in tl for kw in _DECLARE_KEYWORDS):
        return ParsedMessage(
            intent   = Intent.DECLARE_CROP,
            crop     = crop,
            district = district,
            area     = area,
            raw_text = text,
        )

    # 4. Price query check MUST take priority if explicit price/mandi keywords exist
    if any(kw in tl for kw in _PRICE_KEYWORDS):
        return ParsedMessage(
            intent   = Intent.PRICE_QUERY,
            crop     = crop,
            district = district,
            area     = None,
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
