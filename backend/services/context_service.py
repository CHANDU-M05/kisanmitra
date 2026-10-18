"""
backend/services/context_service.py — Session Memory & Context Resolution

Fetches recent chat history and extracts active entities (crop, district)
from recent conversation turns to support multi-turn dialogue in KisanMitra.
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple, List, Dict
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.models import ChatHistory

logger = logging.getLogger("kisanmitra.context")

async def get_recent_history(phone_number: str, db: AsyncSession, limit: int = 5) -> List[Dict[str, str]]:
    """
    Fetch the last `limit` chat history records for a given phone number,
    returned in chronological order (oldest to newest).
    """
    stmt = (
        select(ChatHistory)
        .where(ChatHistory.phone_number == phone_number)
        .order_by(desc(ChatHistory.created_at))
        .limit(limit)
    )
    result = await db.execute(stmt)
    records = result.scalars().all()
    
    # Reverse to chronological order (oldest -> newest)
    records.reverse()
    
    history = []
    for r in records:
        history.append({
            "role": r.role,
            "content": r.message_content,
            "crop": r.crop,
            "district": r.district,
            "intent": r.intent_category
        })
    return history

async def resolve_session_entities(phone_number: str, db: AsyncSession) -> Tuple[Optional[str], Optional[str]]:
    """
    Find the most recent non-null crop and district mentioned in recent active chat history
    for a given phone number.
    """
    stmt = (
        select(ChatHistory.crop, ChatHistory.district)
        .where(ChatHistory.phone_number == phone_number)
        .order_by(desc(ChatHistory.created_at))
        .limit(10)
    )
    result = await db.execute(stmt)
    rows = result.all()
    
    active_crop = None
    active_district = None
    
    for crop, district in rows:
        if not active_crop and crop:
            active_crop = crop
        if not active_district and district:
            active_district = district
        if active_crop and active_district:
            break
            
    return active_crop, active_district
