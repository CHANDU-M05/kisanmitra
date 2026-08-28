"""
tests/test_district_spelling_aliases.py — Test comprehensive district spelling resolution.

Verifies that legacy English spellings, modern official spellings, Kannada script forms,
and Kanglish locatives all resolve cleanly to their canonical district names.
"""

from backend.services.message_handler import resolve_district

DISTRICT_SPELLING_TEST_CASES = [
    # Legacy vs Modern English
    ("Shimoga", "Shivamogga"),
    ("Belgaum", "Belagavi"),
    ("Gulbarga", "Kalaburagi"),
    ("Bangalore", "Bengaluru Urban"),
    ("Mysore", "Mysuru"),
    ("Tumkur", "Tumakuru"),
    ("Davangere", "Davanagere"),
    ("Chikmagalur", "Chikkamagaluru"),
    ("Chickmagalur", "Chikkamagaluru"),
    ("Chikballapur", "Chikkaballapur"),
    ("Coorg", "Kodagu"),
    ("Mangalore", "Dakshina Kannada"),
    ("Mangaluru", "Dakshina Kannada"),
    ("Bijapur", "Vijayapura"),
    ("Bellary", "Ballari"),
    ("Karwar", "Uttara Kannada"),
    ("Hospet", "Vijayanagara"),
    ("Bagalkot", "Bagalkote"),
    ("Chamrajnagar", "Chamarajanagar"),

    # Kannada Script & Locative Stems
    ("ಶಿವಮೊಗ್ಗದಲ್ಲಿ", "Shivamogga"),
    ("ಬೆಳಗಾವಿಯಲ್ಲಿ", "Belagavi"),
    ("ಕಲಬುರಗಿಯಲ್ಲಿ", "Kalaburagi"),
    ("ಬೆಂಗಳೂರಿನಲ್ಲಿ", "Bengaluru Urban"),
    ("ಮೈಸೂರಿನಲ್ಲಿ", "Mysuru"),
    ("ತುಮಕೂರಿನಲ್ಲಿ", "Tumakuru"),
    ("ದಾವಣಗೆರೆಯಲ್ಲಿ", "Davanagere"),
    ("ಚಿಕ್ಕಬಳ್ಳಾಪುರದಲ್ಲಿ", "Chikkaballapur"),
    ("ಕೋಲಾರದಲ್ಲಿ", "Kolar"),
    ("ಹಾಸನದಲ್ಲಿ", "Hassan"),
    ("ಧಾರವಾಡದಲ್ಲಿ", "Dharwad"),

    # Kanglish Romanized Locatives
    ("shimogalli", "Shivamogga"),
    ("belgaumalli", "Belagavi"),
    ("mysorealli", "Mysuru"),
    ("tumkuralli", "Tumakuru"),
    ("kolaralli", "Kolar"),
    ("mandyalli", "Mandya"),
]

def test_all_district_spelling_aliases():
    for raw_input, expected_canonical in DISTRICT_SPELLING_TEST_CASES:
        resolved = resolve_district(raw_input)
        assert resolved == expected_canonical, f"Failed for '{raw_input}': expected '{expected_canonical}', got '{resolved}'"
