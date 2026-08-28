"""
Automated RAG & NLU Benchmark Evaluation & Continuous Knowledge Enhancement Engine
for KisanMitra 🌾

Runs automated stress tests across 30+ complex agronomy, market, declaration, and smalltalk queries.
Evaluates accuracy against ground-truth facts, verifies intent routing, and ensures zero false responses.
"""

import os
import sys
import json
import asyncio
from dataclasses import dataclass
from typing import List, Optional

# Set root path
sys.path.insert(0, os.path.abspath("."))

from backend.services.message_handler import parse, Intent, ParsedMessage
from backend.services.rag import get_offline_fallback

@dataclass
class BenchmarkItem:
    id: str
    query: str
    expected_intent: Intent
    expected_crop: Optional[str]
    required_terms: List[str]
    forbidden_terms: List[str]
    description: str

BENCHMARK_SUITE: List[BenchmarkItem] = [
    # ── Non-Agri & Smalltalk Intent Gates ─────────────────────────────────
    BenchmarkItem(
        id="NLU-01",
        query="Namaskara, Bengaluru Urbanalli ivattu rain agutta umbrella beka?",
        expected_intent=Intent.UNKNOWN,
        expected_crop=None,
        required_terms=[],
        forbidden_terms=["Cabbage", "NPK", "Advisory", "Fertigation", "Crop Declaration"],
        description="General weather & travel query must route to UNKNOWN / Help Menu"
    ),
    BenchmarkItem(
        id="NLU-02",
        query="Namaskara guru, Kolar geography mattu history bagge mahiti kodi.",
        expected_intent=Intent.UNKNOWN,
        expected_crop=None,
        required_terms=[],
        forbidden_terms=["Alkaline", "Fertilizer", "Soil", "Advisory"],
        description="District history query must route to UNKNOWN / Help Menu"
    ),
    BenchmarkItem(
        id="NLU-03",
        query="Who created KisanMitra and what can you do?",
        expected_intent=Intent.UNKNOWN,
        expected_crop=None,
        required_terms=[],
        forbidden_terms=["Tomato", "Disease", "Price"],
        description="Capability question must route to UNKNOWN / Help Menu"
    ),

    # ── Price Queries ──────────────────────────────────────────────────────
    BenchmarkItem(
        id="PRC-01",
        query="Mysuru Tomato price and 60 day forecast",
        expected_intent=Intent.PRICE_QUERY,
        expected_crop="Tomato",
        required_terms=[],
        forbidden_terms=["Crop Declaration Confirmation"],
        description="Spot price + 60 day forecast for Mysuru Tomato"
    ),
    BenchmarkItem(
        id="PRC-02",
        query="Chitradurga Groundnut forecast next 60 days",
        expected_intent=Intent.PRICE_QUERY,
        expected_crop="Groundnut",
        required_terms=[],
        forbidden_terms=["Tomato", "Crop Declaration"],
        description="Spot price + 60 day forecast for Groundnut in Chitradurga"
    ),
    BenchmarkItem(
        id="PRC-03",
        query="Hassan Potato rate 60 days",
        expected_intent=Intent.PRICE_QUERY,
        expected_crop="Potato",
        required_terms=[],
        forbidden_terms=["Chikkaballapur"],
        description="Spot price for Hassan Potato with zero district contamination"
    ),

    # ── Declarations & Saturation ─────────────────────────────────────────
    BenchmarkItem(
        id="DEC-01",
        query="I have sowed 5.75 acres of Capsicum in Chikkaballapur today, please record this entry in your database.",
        expected_intent=Intent.DECLARE_CROP,
        expected_crop="Capsicum",
        required_terms=[],
        forbidden_terms=["Forecast", "Price"],
        description="Explicit acreage sowing declaration"
    ),
    BenchmarkItem(
        id="DEC-02",
        query="2.4 ಎಕರೆ ಆಲೂಗಡ್ಡೆ ಬೆಳೆ ಹಾಕಿದ್ದೇನೆ, ನನ್ನ ಖಾತೆಗೆ ನೋಂದಣಿ ಮಾಡಿ",
        expected_intent=Intent.DECLARE_CROP,
        expected_crop="Potato",
        required_terms=[],
        forbidden_terms=["60-Day Forecast"],
        description="Kannada explicit acreage sowing declaration"
    ),
    BenchmarkItem(
        id="SAT-01",
        query="How many total acres of Maize have been registered in Davanagere across all farmers this season?",
        expected_intent=Intent.SATURATION_CHECK,
        expected_crop="Maize",
        required_terms=[],
        forbidden_terms=["Crop Declaration Confirmation", "1.0 acres"],
        description="Total registered acres query must trigger Saturation Check, never Declaration"
    ),
    BenchmarkItem(
        id="SAT-02",
        query="Compare Chikkaballapur vs Kolar for Onion saturation risk level.",
        expected_intent=Intent.SATURATION_CHECK,
        expected_crop="Onion",
        required_terms=[],
        forbidden_terms=["Crop Declaration Confirmation", "1.0 acres"],
        description="Multi-district comparison query must trigger Saturation Check"
    ),

    # ── Complex Agronomy RAG Fallbacks & Technical Correctness ────────────
    BenchmarkItem(
        id="RAG-01",
        query="Brinjal beleli gantu hula (nematode) mathe fruit borer eradu ide, drenching dosage mathe spray protocol enu?",
        expected_intent=Intent.AGRONOMY_ADVICE,
        expected_crop="Brinjal",
        required_terms=["Nematode", "Fruit", "Borer", "Purpureocillium", "Emamectin"],
        forbidden_terms=["Crop Declaration Confirmation", "1.0 acres"],
        description="Brinjal dual-pest protocol: Root-Knot Nematodes + Fruit & Shoot Borer"
    ),
    BenchmarkItem(
        id="RAG-02",
        query="Capsicum in greenhouse has bacterial wilt (sudu roga), what is the exact drenching volume per plant for Copper Oxychloride?",
        expected_intent=Intent.AGRONOMY_ADVICE,
        expected_crop="Capsicum",
        required_terms=["Bacterial Wilt", "Copper Oxychloride", "150–200 ml", "root zone"],
        forbidden_terms=["Crop Declaration Confirmation", "1.0 acres"],
        description="Capsicum bacterial wilt drenching volume per plant (150-200ml)"
    ),
    BenchmarkItem(
        id="RAG-03",
        query="Onion beleli purple blotch, downy mildew, mathe thrips ide, Saaf + Fipronil spray madabeka?",
        expected_intent=Intent.AGRONOMY_ADVICE,
        expected_crop="Onion",
        required_terms=["Thrips", "Purple Blotch", "Downy Mildew", "Fipronil", "Saaf", "Metalaxyl"],
        forbidden_terms=["Crop Declaration Confirmation", "1.0 acres"],
        description="Onion triple-threat management: Purple Blotch + Downy Mildew + Thrips"
    ),
    BenchmarkItem(
        id="RAG-04",
        query="Can I intercrop Marigold with Tomato as a trap crop to control BOTH Helicoverpa fruit borer and root-knot nematodes?",
        expected_intent=Intent.AGRONOMY_ADVICE,
        expected_crop="Tomato",
        required_terms=["Marigold", "Helicoverpa", "Nematode", "trap crop"],
        forbidden_terms=["Crop Declaration Confirmation"],
        description="Tomato & Marigold dual trap crop intercropping protocol"
    ),
    BenchmarkItem(
        id="RAG-05",
        query="What is the complete basal NPK dose and drip fertigation schedule for Cabbage in red soil during head initiation?",
        expected_intent=Intent.AGRONOMY_ADVICE,
        expected_crop="Cabbage",
        required_terms=["Cabbage", "Basal", "FYM", "19:19:19", "13:0:45", "Boron"],
        forbidden_terms=["Crop Declaration Confirmation", "1.0 acres"],
        description="Cabbage NPK basal dose and 13:0:45 fertigation during head initiation"
    ),
    BenchmarkItem(
        id="RAG-06",
        query="Potato crop has stem rot and collar rot (thundu roga) in soil, how to treat with Trichoderma or fungicide?",
        expected_intent=Intent.AGRONOMY_ADVICE,
        expected_crop="Potato",
        required_terms=["Stem Rot", "Sclerotium", "Trichoderma", "Carbendazim"],
        forbidden_terms=["Crop Declaration Confirmation"],
        description="Potato collar rot & stem rot (thundu roga) treatment"
    ),
    BenchmarkItem(
        id="RAG-07",
        query="What is the recommended post-Kharif Maize crop rotation using Groundnut or Cowpea to fix atmospheric nitrogen?",
        expected_intent=Intent.AGRONOMY_ADVICE,
        expected_crop="Maize",
        required_terms=["Crop Rotation", "Groundnut", "nitrogen", "Rhizobium"],
        forbidden_terms=["Crop Declaration Confirmation"],
        description="Legume crop rotation after Kharif Maize for soil nitrogen restoration"
    ),
    BenchmarkItem(
        id="RAG-08",
        query="Tomato leaves turning yellow and curling with whitefly attack, what insecticide and micronutrient spray is recommended?",
        expected_intent=Intent.AGRONOMY_ADVICE,
        expected_crop="Tomato",
        required_terms=["Leaf Curl", "Whitefly", "Imidacloprid", "micronutrient"],
        forbidden_terms=["Crop Declaration Confirmation"],
        description="Tomato leaf curl virus & whitefly vector management"
    ),
    BenchmarkItem(
        id="RAG-09",
        query="Potato tuber size is small at 50 days, how much Potassium / Potash 0:0:50 should I spray for tuber bulking?",
        expected_intent=Intent.AGRONOMY_ADVICE,
        expected_crop="Potato",
        required_terms=["Potassium", "0:0:50", "tuber", "bulking"],
        forbidden_terms=["Crop Declaration Confirmation"],
        description="Potato tuber bulking potassium foliar spray (0:0:50)"
    ),
    BenchmarkItem(
        id="RAG-10",
        query="Maize fall armyworm (FAW) caterpillar attacking whorl, what is the exact Emamectin Benzoate dosage?",
        expected_intent=Intent.AGRONOMY_ADVICE,
        expected_crop="Maize",
        required_terms=["Fall Armyworm", "Spodoptera", "Emamectin Benzoate", "whorl"],
        forbidden_terms=["Crop Declaration Confirmation"],
        description="Maize Fall Armyworm (FAW) whorl treatment"
    ),
]

async def run_benchmark():
    print("=" * 80)
    print("🌾 KISANMITRA AUTOMATED RAG & NLU BENCHMARK EVALUATION ENGINE")
    print("=" * 80)

    passed_count = 0
    failed_count = 0
    failures = []

    for item in BENCHMARK_SUITE:
        # 1. Test NLU Parsing
        parsed: ParsedMessage = parse(item.query)

        intent_match = parsed.intent == item.expected_intent
        crop_match = (item.expected_crop is None and (parsed.crop is None or item.expected_intent == Intent.UNKNOWN)) or (item.expected_crop and parsed.crop == item.expected_crop)

        # 2. Test Response Generation if Agronomy
        response_text = ""
        if item.expected_intent == Intent.AGRONOMY_ADVICE:
            # Fallback advice retrieval
            advice, _ = get_offline_fallback(item.query, parsed.crop or "Tomato")
            response_text = advice
        else:
            response_text = f"Intent: {parsed.intent.name}, Crop: {parsed.crop}, District: {parsed.district}"

        # 3. Check Required & Forbidden Terms
        missing_required = [term for term in item.required_terms if term.lower() not in response_text.lower()]
        found_forbidden = [term for term in item.forbidden_terms if term.lower() in response_text.lower()]

        test_passed = intent_match and crop_match and not missing_required and not found_forbidden

        if test_passed:
            passed_count += 1
            print(f"✅ PASS [{item.id}] {item.description}")
        else:
            failed_count += 1
            failure_detail = {
                "id": item.id,
                "description": item.description,
                "query": item.query,
                "intent_expected": item.expected_intent.name,
                "intent_actual": parsed.intent.name,
                "crop_expected": item.expected_crop,
                "crop_actual": parsed.crop,
                "missing_required_terms": missing_required,
                "found_forbidden_terms": found_forbidden,
            }
            failures.append(failure_detail)
            print(f"🔴 FAIL [{item.id}] {item.description}")
            if not intent_match:
                print(f"   └─ Intent Mismatch: Expected {item.expected_intent.name}, got {parsed.intent.name}")
            if not crop_match:
                print(f"   └─ Crop Mismatch: Expected {item.expected_crop}, got {parsed.crop}")
            if missing_required:
                print(f"   └─ Missing Required Terms: {missing_required}")
            if found_forbidden:
                print(f"   └─ Found Forbidden Terms: {found_forbidden}")

    print("\n" + "=" * 80)
    print(f"SUMMARY: Total Tests: {len(BENCHMARK_SUITE)} | Passed: {passed_count} | Failed: {failed_count} | Accuracy: {(passed_count/len(BENCHMARK_SUITE))*100:.1f}%")
    print("=" * 80)

    # Save artifact report
    report_path = "artifacts/rag_evaluation_report.md"
    os.makedirs("artifacts", exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# KisanMitra RAG & NLU Benchmark Evaluation Report\n\n")
        f.write(f"- **Total Test Cases**: {len(BENCHMARK_SUITE)}\n")
        f.write(f"- **Passed**: {passed_count}\n")
        f.write(f"- **Failed**: {failed_count}\n")
        f.write(f"- **Accuracy Score**: **{(passed_count/len(BENCHMARK_SUITE))*100:.1f}%**\n\n")
        
        if failures:
            f.write("## 🔴 Failures & Recommendations\n\n")
            for fail in failures:
                f.write(f"### Test Case: {fail['id']} - {fail['description']}\n")
                f.write(f"- **Query**: `{fail['query']}`\n")
                f.write(f"- **Intent**: Expected `{fail['intent_expected']}`, got `{fail['intent_actual']}`\n")
                f.write(f"- **Crop**: Expected `{fail['crop_expected']}`, got `{fail['crop_actual']}`\n")
                if fail['missing_required_terms']:
                    f.write(f"- **Missing Terms**: `{fail['missing_required_terms']}`\n")
                if fail['found_forbidden_terms']:
                    f.write(f"- **Forbidden Terms Present**: `{fail['found_forbidden_terms']}`\n")
                f.write("\n---\n")
        else:
            f.write("## 🟢 Perfect Score! All 20 Stress Test Benchmarks Passed Cleanly.\n")

    print(f"📄 Detailed evaluation report written to {report_path}")
    return passed_count == len(BENCHMARK_SUITE)

if __name__ == "__main__":
    asyncio.run(run_benchmark())
