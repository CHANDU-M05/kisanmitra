"""
scratch/test_context_memory.py — Async verification of WhatsApp session memory
"""
import asyncio
import os
from pathlib import Path

os.environ["DB_HAS_PGVECTOR"] = "0"
os.environ["DB_HAS_POSTGIS"] = "0"

from backend.core.database import AsyncSessionLocal, engine, Base
from backend.services import context_service
from backend.core.models import ChatHistory

async def run_test():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as db:
        test_phone = "+919876543210"
        
        print("=== 1. POPULATING MOCK MULTI-TURN CHAT HISTORY ===")
        db.add_all([
            ChatHistory(
                phone_number=test_phone,
                role="user",
                message_content="ಟೊಮ್ಯಾಟೊ ಬೆಲೆ ಎಷ್ಟು?",
                intent_category="PRICE_QUERY",
                crop="Tomato",
                district="Kolar"
            ),
            ChatHistory(
                phone_number=test_phone,
                role="assistant",
                message_content="Kolar Tomato price is 1500 Rs/quintal",
                intent_category="PRICE_QUERY",
                crop="Tomato",
                district="Kolar"
            ),
            ChatHistory(
                phone_number=test_phone,
                role="user",
                message_content="ಅಂಗಮಾರಿ ರೋಗಕ್ಕೆ ಏನು ಮಾಡಬೇಕು?",
                intent_category="AGRONOMY_ADVICE",
                crop="Tomato",
                district="Kolar"
            ),
        ])
        await db.commit()
        
        print("=== 2. TESTING SESSION ENTITY RESOLUTION ===")
        crop, district = await context_service.resolve_session_entities(test_phone, db)
        print(f"Resolved Session Entities for {test_phone}: Crop = '{crop}', District = '{district}'")
        
        print("\n=== 3. TESTING RECENT HISTORY FETCH FOR RAG PROMPT ===")
        history = await context_service.get_recent_history(test_phone, db, limit=4)
        print(f"Fetched {len(history)} recent turns:")
        for h in history:
            print(f"  [{h['role'].upper()}] ({h['intent']}): {h['content']}")

if __name__ == "__main__":
    asyncio.run(run_test())
