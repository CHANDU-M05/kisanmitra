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

# Allow importing api.core from the project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.core.logging_config import setup_kisanmitra_logging
logger = setup_kisanmitra_logging("kisanmitra.ingestion")

from pydantic import BaseModel, Field
from openai import AsyncOpenAI
from sqlalchemy import insert

from api.core.config import settings
from api.core.database import AsyncSessionLocal
from api.core.models import KnowledgeChunk, _HAS_PGVECTOR

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

client = AsyncOpenAI(api_key=settings.openai_api_key)

async def call_with_retry(func, *args, **kwargs):
    """Robust retry logic with exponential backoff."""
    max_retries = 5
    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            if "rate_limit" in str(e).lower() or "timeout" in str(e).lower() or attempt < 2:
                wait_time = (2 ** attempt) + 1
                print(f"⚠️ OpenAI API Error: {e}. Retrying in {wait_time}s... (Attempt {attempt+1}/{max_retries})")
                await asyncio.sleep(wait_time)
            else:
                raise e
    raise Exception("Max retries exceeded for OpenAI API call")

async def process_and_ingest_bulletin(raw_text: str, source_name: str):
    if not settings.openai_api_key:
        print("❌ OPENAI_API_KEY not set.")
        return

    print("🧠 Extracting structured agronomy chunks...")
    
    try:
        # Pass 1: Agentic Extraction (with retry)
        completion = await call_with_retry(
            client.beta.chat.completions.parse,
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": BEAST_PROMPT},
                {"role": "user", "content": f"Extract data from this ICAR bulletin:\n\n{raw_text}"}
            ],
            response_format=DocumentExtraction,
        )
        
        extracted_data = completion.choices[0].message.parsed
        if not extracted_data or not extracted_data.chunks:
            print("⚠️ No actionable data found.")
            return

        print(f"🧬 Generating embeddings for {len(extracted_data.chunks)} chunks...")
        texts_to_embed = [chunk.actionable_advice for chunk in extracted_data.chunks]
        
        # Pass 2: Batch Embedding Generation (with retry)
        embedding_response = await call_with_retry(
            client.embeddings.create,
            model="text-embedding-3-small",
            input=texts_to_embed
        )
        
        print("💾 Sinking to KisanMitra Database...")
        async with AsyncSessionLocal() as session:
            async with session.begin():
                for i, chunk in enumerate(extracted_data.chunks):
                    vector = embedding_response.data[i].embedding
                    
                    stmt = insert(KnowledgeChunk).values(
                        crop=chunk.crop,
                        category=chunk.category,
                        districts=chunk.districts,
                        content=chunk.actionable_advice,
                        keywords=chunk.keywords,
                        source=source_name,
                        embedding=vector if _HAS_PGVECTOR else str(vector)
                    )
                    await session.execute(stmt)
            print(f"✅ Ingestion Complete: {len(extracted_data.chunks)} chunks added.")

    except Exception as e:
        print(f"❌ Error during ingestion: {e}")

async def main():
    # Example usage with dummy text if no file provided
    if len(sys.argv) < 2:
        print("Usage: python scripts/seed_knowledge.py <path_to_txt_file>")
        print("Running with sample text for demonstration...")
        sample_text = """
        ICAR-KVK Kolar Bulletin 2024
        Tomato: Management of Leaf Curl Virus. 
        Symptoms: Downward curling and yellowing of leaves.
        Control: Spray Imidacloprid 0.3ml/liter. Maintain 5m distance between plots.
        District: Kolar, Chikkaballapur.
        """
        await process_and_ingest_bulletin(sample_text, "sample_bulletin_2024")
    else:
        path = Path(sys.argv[1])
        if not path.exists():
            print(f"File not found: {path}")
            return
        raw_text = path.read_text()
        await process_and_ingest_bulletin(raw_text, path.name)

if __name__ == "__main__":
    asyncio.run(main())
