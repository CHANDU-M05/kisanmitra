from fastapi import APIRouter, Depends
from sqlalchemy import select, func, case, desc
from sqlalchemy.ext.asyncio import AsyncSession
from backend.core.database import get_db
from backend.core.models import ChatHistory, AdminUser
from backend.routers.auth import get_current_user

router = APIRouter(prefix="/analytics", tags=["analytics"])

@router.get("/rag-health")
async def get_rag_health(
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    # 1. Base Aggregations
    stmt = select(
        func.count().label("total"),
        func.count(ChatHistory.feedback_score).label("with_feedback"),
        func.sum(case((ChatHistory.feedback_score == 1, 1), else_=0)).label("positive"),
        func.sum(case((ChatHistory.feedback_score == -1, 1), else_=0)).label("negative")
    ).where(ChatHistory.role == "assistant")
    
    res = await db.execute(stmt)
    stats = res.mappings().one()
    
    total = stats["total"] or 0
    with_feedback = stats["with_feedback"] or 0
    positive = stats["positive"] or 0
    
    engagement_rate = (with_feedback / total * 100) if total > 0 else 0
    accuracy_score = (positive / with_feedback * 100) if with_feedback > 0 else 0
    
    # 2. Failure Hotspots
    hotspot_stmt = select(
        ChatHistory.intent_category,
        func.count().label("failure_count")
    ).where(
        ChatHistory.role == "assistant",
        ChatHistory.feedback_score == -1
    ).group_by(ChatHistory.intent_category).order_by(desc("failure_count")).limit(5)
    
    hotspot_res = await db.execute(hotspot_stmt)
    hotspots = [
        {"intent": row.intent_category, "count": row.failure_count} 
        for row in hotspot_res
    ]
    
    return {
        "total_interactions": total,
        "engagement_rate": round(engagement_rate, 1),
        "accuracy_score": round(accuracy_score, 1),
        "failure_hotspots": hotspots
    }


@router.get("/bot/history")
async def get_bot_history(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
) -> list:
    result = await db.execute(
        select(ChatHistory)
        .order_by(ChatHistory.created_at.desc())
        .limit(limit)
    )
    history = result.scalars().all()
    return [
        {
            "id": str(item.id),
            "phone_number": item.phone_number,
            "role": item.role,
            "message_content": item.message_content,
            "intent_category": item.intent_category,
            "feedback_score": item.feedback_score,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }
        for item in history
    ]
