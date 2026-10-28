"""
backend/core/phone.py — Indian mobile-number normalisation & validation.

The web declaration form (/farmer/declare) collects a real mobile number typed
by a farmer or field agent, but historically it was stored verbatim, so the
registry accumulated inconsistent formats: "+91 98765 43210", "09876543210",
"919876543210", and outright invalid values. This module gives one canonical
form — a bare 10-digit national number starting 6-9 — used both to normalise
acceptable inputs and to reject the rest at the schema boundary.

NOTE: historically the Telegram channel stored a Telegram *user id* in
CropDeclaration.phone (backend/routers/conversation.py::_handle_declare). As of
the Oct 2026 identity split, new Telegram rows store the id in sender_id with
channel='telegram' and phone NULL; only LEGACY rows still carry ids in phone.
Telegram ids are intentionally NOT routed through this validator — only
human-entered web numbers are.
"""
from __future__ import annotations

import re

_DIGITS = re.compile(r"\D")
_IN_MOBILE = re.compile(r"[6-9]\d{9}")


def normalize_phone(raw: str | None) -> str:
    """Reduce any common input to a bare 10-digit national number.

    Strips all non-digits, then removes a leading country code (+91/91) or a
    leading trunk prefix (0). Returns the digit string (possibly still invalid,
    e.g. too short) so callers can decide whether to reject; use
    is_valid_indian_mobile() to check the result.
    """
    digits = _DIGITS.sub("", raw or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]          # 919876543210 -> 9876543210
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]          # 09876543210  -> 9876543210
    return digits


def is_valid_indian_mobile(raw: str | None) -> bool:
    """True iff raw normalises to a valid 10-digit Indian mobile (starts 6-9)."""
    return bool(_IN_MOBILE.fullmatch(normalize_phone(raw)))
