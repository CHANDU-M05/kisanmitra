import pytest
from backend.services.message_handler import parse, Intent, resolve_crop, resolve_district

def test_resolve_crop():
    # Exact match
    assert resolve_crop("Tomato") == "Tomato"
    # Alias match (Kannada)
    assert resolve_crop("ನಾನು ಟೊಮ್ಯಾಟೊ ಬೆಳೆದಿದ್ದೇನೆ") == "Tomato"
    # Fuzzy match (typo)
    assert resolve_crop("tamato") == "Tomato"
    # No match
    assert resolve_crop("apple") is None

def test_resolve_district():
    assert resolve_district("Chikkaballapur") == "Chikkaballapur"
    assert resolve_district("ಚಿಕ್ಕಬಳ್ಳಾಪುರದಲ್ಲಿ") == "Chikkaballapur"
    assert resolve_district("kolar") == "Kolar"
    assert resolve_district("unknown") is None

def test_parse_price_query():
    msg = parse("ಟೊಮ್ಯಾಟೊ ಬೆಲೆ ಎಷ್ಟು?")
    assert msg.intent == Intent.PRICE_QUERY
    assert msg.crop == "Tomato"
    
    msg = parse("What is the mandi rate for Potato?")
    assert msg.intent == Intent.PRICE_QUERY
    assert msg.crop == "Potato"

def test_parse_declare_crop():
    msg = parse("ನಾನು 2 ಎಕರೆ ಟೊಮ್ಯಾಟೊ ಬೆಳೆ ಹಾಕಿದ್ದೇನೆ")
    assert msg.intent == Intent.DECLARE_CROP
    assert msg.crop == "Tomato"
    assert msg.area == 2.0

    msg = parse("3 acres onion declare")
    assert msg.intent == Intent.DECLARE_CROP
    assert msg.crop == "Onion"
    assert msg.area == 3.0

def test_parse_agronomy_advice():
    msg = parse("ಟೊಮ್ಯಾಟೊ ರೋಗ ಬಗ್ಗೆ ಮಾಹಿತಿ ಕೊಡಿ")
    assert msg.intent == Intent.AGRONOMY_ADVICE
    assert msg.crop == "Tomato"

    msg = parse("Potato fertilizer schedule")
    assert msg.intent == Intent.AGRONOMY_ADVICE
    assert msg.crop == "Potato"

def test_parse_saturation():
    msg = parse("Tomato saturation check")
    assert msg.intent == Intent.SATURATION_CHECK
    assert msg.crop == "Tomato"

def test_parse_unknown():
    msg = parse("Hello, how are you?")
    assert msg.intent == Intent.UNKNOWN
    assert msg.crop is None
