import asyncio
import os
import sys

# Ensure root import path
sys.path.insert(0, os.path.abspath("."))

from backend.services.message_handler import parse, Intent, ParsedMessage

test_queries = [
    ("Namaskara, Bengaluru Urbanalli ivattu rain agutta umbrella beka?", Intent.UNKNOWN, None),
    ("Mysuru Tomato price", Intent.PRICE_QUERY, None),
    ("Chitradurga Groundnut forecast", Intent.PRICE_QUERY, None),
    ("Hassan Potato forecast", Intent.PRICE_QUERY, None),
    ("I have sowed 5.75 acres of Capsicum in Chikkaballapur today, please record this entry in your database.", Intent.DECLARE_CROP, 5.75),
    ("2.4 ಎಕರೆ ಆಲೂಗಡ್ಡೆ ಬೆಳೆ ಹಾಕಿದ್ದೇನೆ", Intent.DECLARE_CROP, 2.4),
    ("4.2 acres Groundnut sowed today", Intent.DECLARE_CROP, 4.2),
    ("How many total acres of Maize have been registered in Davanagere across all farmers this season?", Intent.SATURATION_CHECK, None),
    ("Compare Chikkaballapur vs Kolar for Onion saturation risk level.", Intent.SATURATION_CHECK, None),
    ("Brinjal beleli gantu hula mathe fruit borer drenching dosage mathe spray protocol enu?", Intent.AGRONOMY_ADVICE, None),
    ("Capsicum in greenhouse has bacterial wilt, what is exact drenching volume per plant?", Intent.AGRONOMY_ADVICE, None),
    ("Onion purple blotch downy mildew thrips Saaf Fipronil spray madabeka?", Intent.AGRONOMY_ADVICE, None),
    ("Can I intercrop Marigold with Tomato to control BOTH Helicoverpa fruit borer and root-knot nematodes?", Intent.AGRONOMY_ADVICE, None),
    ("What is the complete basal NPK dose and drip fertigation schedule for Cabbage in red soil during head initiation?", Intent.AGRONOMY_ADVICE, None),
]

def run_tests():
    print("\n--- RUNNING COMPULSORY INTENT & DECLARATION VERIFICATION ---")
    all_pass = True
    for idx, (query, expected_intent, expected_area) in enumerate(test_queries, 1):
        parsed: ParsedMessage = parse(query)
        intent_ok = parsed.intent == expected_intent
        area_ok = (expected_area is None and parsed.area is None) or (expected_area is not None and parsed.area == expected_area)
        
        status = "✅ PASS" if (intent_ok and area_ok) else "🔴 FAIL"
        if not (intent_ok and area_ok):
            all_pass = False
            
        print(f"Q{idx}: [{status}] Intent: {parsed.intent.name} (Exp: {expected_intent.name}), Area: {parsed.area} (Exp: {expected_area}) | Query: '{query[:50]}...'")

    print("\nALL VERIFICATION TESTS COMPLETED:", "✅ SUCCESS" if all_pass else "🔴 FAILED")
    return all_pass

if __name__ == "__main__":
    run_tests()
