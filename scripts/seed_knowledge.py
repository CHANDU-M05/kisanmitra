#!/usr/bin/env python3
"""
scripts/seed_knowledge.py

Agentic Ingestion Pipeline for KisanMitra.
Extracts "Atomic Agronomy Propositions" from raw bulletins using GPT-4o-mini
and sinks them into PostgreSQL with embeddings.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import List

# Allow importing backend.core from the project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.logging_config import setup_kisanmitra_logging
logger = setup_kisanmitra_logging("kisanmitra.ingestion")

from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from sqlalchemy import insert, select

from backend.core.config import settings
from backend.core.database import AsyncSessionLocal
from backend.core.models import KnowledgeChunk, _HAS_PGVECTOR

# ── Schemas ───────────────────────────────────────────────

class AgronomyChunk(BaseModel):
    crop: str = Field(description="Primary crop (e.g., Tomato, Ragi). Use 'General' if no specific crop.")
    category: str = Field(description="Category: Pest Management, Disease, Fertilizer, Weather, or Market.")
    districts: List[str] = Field(description="Targeted districts (e.g., Kolar, Chikkaballapur).")
    actionable_advice: str = Field(description="A clean, highly specific, self-contained paragraph of advice.")
    keywords: List[str] = Field(description="5-7 searchable terms for hybrid search matching.")

class DocumentExtraction(BaseModel):
    chunks: List[AgronomyChunk]

# ── Prompt ────────────────────────────────────────────────

BEAST_PROMPT = """
You are the lead Agronomy Intelligence Engine for KisanMitra.
Your task is to process raw, unstructured text extracted from ICAR/KVK agricultural bulletins and convert it into clean, self-contained "Knowledge Chunks."

Raw agronomy documents often contain broken tables, fragmented sentences, and mixed contexts. Your job is to synthesize this into highly specific, actionable advice units.

RULES:
1. ATOMICITY: Each chunk must be a single, complete thought (e.g., "Management of Leaf Curl in Tomatoes" or "Rainfall forecast for Kolar"). Do not create chunks that require outside context to understand.
2. FIX THE FORMATTING: Convert tabular data (like NPK ratios, seed rates, or pesticide doses) into clear, natural language sentences.
3. ENTITY TAGGING: Accurately tag the specific crop and district (e.g., Kolar, Chikkaballapur). If the advice applies broadly, use "All".
4. TRANSLITERATION AWARENESS: If the raw text contains Kannada terms written in English (like 'Ragi' or 'Bele'), retain them alongside the English equivalent to support our fuzzy matching engine.
5. NO FLUFF: Discard administrative headers, page numbers, and table of contents. Extract only farming intelligence.
"""

# ── Pipeline ──────────────────────────────────────────────

client = genai.Client(api_key=settings.gemini_api_key.get_secret_value())

async def call_with_retry(func, *args, **kwargs):
    """Robust retry logic with exponential backoff."""
    max_retries = 5
    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            if "rate_limit" in str(e).lower() or "timeout" in str(e).lower() or attempt < 2:
                wait_time = (2 ** attempt) + 1
                print(f"⚠️ API Error: {e}. Retrying in {wait_time}s... (Attempt {attempt+1}/{max_retries})")
                await asyncio.sleep(wait_time)
            else:
                raise e
    raise Exception("Max retries exceeded for API call")

async def process_and_ingest_bulletin(raw_text: str, source_name: str):
    if not settings.gemini_api_key:
        print("❌ GEMINI_API_KEY not set.")
        return

    print("🧠 Extracting structured agronomy chunks...")
    
    try:
        # Pass 1: Agentic Extraction (with retry)
        completion = await call_with_retry(
            client.aio.models.generate_content,
            model='gemini-2.5-flash',
            contents=f"Extract data from this ICAR bulletin:\n\n{raw_text}",
            config=types.GenerateContentConfig(
                system_instruction=BEAST_PROMPT,
                response_mime_type="application/json",
                response_schema=DocumentExtraction,
                temperature=0.2,
            ),
        )
        
        extracted_data = DocumentExtraction.model_validate_json(completion.text)
        if not extracted_data or not extracted_data.chunks:
            print("⚠️ No actionable data found.")
            return

        print(f"🧬 Generating embeddings for {len(extracted_data.chunks)} chunks...")
        # CRITICAL: embed with the SAME model as query-time retrieval (backend.services.rag.embed_text).
        # Using a different model here would place ingest vectors in a different semantic
        # space than query vectors, silently breaking pgvector cosine similarity ranking.
        from backend.services.rag import embed_text

        vectors: list = []
        for chunk in extracted_data.chunks:
            vector = None
            if _HAS_PGVECTOR:
                vector = await call_with_retry(embed_text, chunk.actionable_advice)
            vectors.append(vector)

        print("💾 Sinking to KisanMitra Database...")
        async with AsyncSessionLocal() as session:
            async with session.begin():
                for i, chunk in enumerate(extracted_data.chunks):
                    vector = vectors[i]

                    # Idempotent re-seeding: bulletins are deterministic, so an
                    # identical (source, content) row is skipped instead of
                    # duplicated — reruns can never pollute retrieval ranking.
                    dup = (await session.execute(
                        select(KnowledgeChunk.id).where(
                            KnowledgeChunk.source == source_name,
                            KnowledgeChunk.content == chunk.actionable_advice,
                        ).limit(1)
                    )).scalar_one_or_none()
                    if dup is not None:
                        print(f"   ↷ skipping duplicate chunk ({chunk.crop}/{chunk.category})")
                        continue

                    stmt = insert(KnowledgeChunk).values(
                        crop=chunk.crop,
                        category=chunk.category,
                        districts=chunk.districts,
                        content=chunk.actionable_advice,
                        keywords=chunk.keywords,
                        source=source_name,
                        embedding=vector if _HAS_PGVECTOR else (str(vector) if vector else None)
                    )
                    await session.execute(stmt)
            print(f"✅ Ingestion Complete: {len(extracted_data.chunks)} chunks added.")

    except Exception as e:
        print(f"❌ Error during ingestion: {e}")

async def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/seed_knowledge.py <path_to_txt_file> [--rule-based]")
        print("Running with sample text for demonstration...")
        sample_text = """
        ICAR-KVK Kolar Bulletin 2024
        Tomato: Management of Leaf Curl Virus. 
        Symptoms: Downward curling and yellowing of leaves.
        Control: Spray Imidacloprid 0.3ml/liter. Maintain 5m distance between plots.
        District: Kolar, Chikkaballapur.
        """
        await process_and_ingest_bulletin(sample_text, "sample_bulletin_2024")
        return

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"File not found: {path}")
        return
    raw_text = path.read_text()

    if "--rule-based" in sys.argv:
        # Deterministic ingestion for already-structured bulletins. The LLM
        # extraction pass is skipped entirely — important because the Gemini
        # free tier caps generateContent at 20 requests/day and advisory
        # traffic routinely spends the quota, which would block seeding.
        await ingest_rule_based(path, raw_text)
    else:
        await process_and_ingest_bulletin(raw_text, path.name)


CROP_WORDS = ["tomato", "potato", "onion", "brinjal", "capsicum", "maize",
              "cabbage", "ragi", "groundnut"]
CATEGORY_WORDS = {
    "Fertilizer": ["npk", "fertilizer", "potash", "fertigation", "dose", "nutrition"],
    "Disease": ["rot", "blight", "wilt", "curl", "blast", "virus", "mildew"],
    "Pest Management": ["worm", "thrips", "nematode", "borer", "moth", "pest", "armyworm"],
    "Weather": ["rainfall", "drought", "forecast"],
}


async def ingest_rule_based(path: Path, raw_text: str):
    import re as _re
    sections = _re.split(r"(?m)^BULLETIN \d+ — ", raw_text)[1:]
    if not sections:
        print("⚠️ No 'BULLETIN n — …' sections found.")
        return

    records = []
    for sec in sections:
        header, _, body = sec.partition("\n")
        body = body.strip()
        low = header.lower()
        crop = next((w.capitalize() for w in CROP_WORDS if w in low), "General")
        category = next((c for c, kws in CATEGORY_WORDS.items() if any(k in low for k in kws)), "General")
        districts = ["Kolar", "Chikkaballapur"] if "kolar" in body.lower() else ["All"]
        keywords = sorted({w for w in _re.findall(r"[A-Za-z]{4,}", header.lower())
                           if w not in {"bulletin", "management", "and"}})[:7]
        records.append((crop, category, districts, f"{header.strip()}. {body}", keywords))

    from backend.services.rag import embed_text
    async with AsyncSessionLocal() as session:
        async with session.begin():
            for crop, category, districts, content, keywords in records:
                dup = (await session.execute(
                    select(KnowledgeChunk.id).where(
                        KnowledgeChunk.source == path.name,
                        KnowledgeChunk.content == content,
                    ).limit(1)
                )).scalar_one_or_none()
                if dup is not None:
                    print(f"   ↷ skipping duplicate chunk ({crop}/{category})")
                    continue
                vector = await call_with_retry(embed_text, content) if _HAS_PGVECTOR else None
                await session.execute(insert(KnowledgeChunk).values(
                    crop=crop, category=category, districts=districts,
                    content=content, keywords=keywords, source=path.name,
                    embedding=vector,
                ))
    print(f"✅ Rule-based ingestion complete: {len(records)} bulletins processed.")

if __name__ == "__main__":
    asyncio.run(main())
