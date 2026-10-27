"""
tests/test_phone_validation.py — Indian mobile normalisation + web-form guard.

Registry incident 2026-10-27: the /farmer/declare web form stored the phone
field verbatim, so "+91 ...", "0...", 12-digit and outright non-mobile values
(e.g. Telegram user ids like 1534422727, or "9480") landed in the farmers
registry. normalize_phone/is_valid_indian_mobile give one canonical form and
DeclareRequest now rejects anything that isn't a real 10-digit mobile.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.core.phone import is_valid_indian_mobile, normalize_phone
from backend.schemas import DeclareRequest


@pytest.mark.parametrize("raw,expected", [
    ("9876543210", "9876543210"),
    ("+91 98765 43210", "9876543210"),
    ("919876543210", "9876543210"),
    ("09876543210", "9876543210"),
    ("0 987-654-3210", "9876543210"),
    ("  9876543210  ", "9876543210"),
])
def test_normalize_accepts_common_formats(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", [
    "9876543210", "+91-9876543210", "09876543210", "919876543210",
])
def test_valid_mobiles_pass(raw):
    assert is_valid_indian_mobile(raw) is True


@pytest.mark.parametrize("bad", [
    "1534422727",   # starts with 1 (a Telegram id, not a mobile)
    "5563593147",   # starts with 5
    "9480",         # far too short
    "81231143120",  # 11 digits, not a +91/0 form
    "",             # empty
    "abcdefghij",   # non-numeric
])
def test_invalid_mobiles_rejected(bad):
    assert is_valid_indian_mobile(bad) is False


def _declare(phone):
    return DeclareRequest(
        farmer_name="Test Farmer", phone=phone, village="V",
        district="Kolar", crop="Tomato", area_acres=1.0,
    )


def test_declare_request_normalizes_phone():
    req = _declare("+91 98765 43210")
    assert req.phone == "9876543210"


def test_declare_request_rejects_invalid_phone():
    with pytest.raises(ValidationError):
        _declare("1534422727")
