from fastapi import APIRouter, Depends, Header, HTTPException
import logging
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uuid import UUID
from backend.core.config import settings
from backend.core.database import get_db
from backend.core.models import CropDeclaration, AdminUser, ChatHistory
from backend.routers.auth import get_current_user
from backend.schemas import DeclareRequest
from backend.services import farmer_service

logger = logging.getLogger("kisanmitra.farmers")
router = APIRouter(tags=["farmers"])

@router.post("/farmer/declare")
async def declare_crop(
    req: DeclareRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    declaration = CropDeclaration(
        farmer_name=req.farmer_name,
        phone=req.phone,
        village=req.village,
        district=req.district,
        crop=req.crop,
        area_acres=req.area_acres,
        season=req.season,
        trust_score=0.85,
        satellite_status="pending",
    )
    db.add(declaration)
    try:
        await db.commit()
        await db.refresh(declaration)
    except Exception:
        await db.rollback()
        raise HTTPException(500, "Declaration could not be saved — DB error.")

    sat   = await farmer_service.calc_saturation(req.district, req.crop, req.season, db)
    reply = (
        f"ನಮಸ್ಕಾರ {req.farmer_name}! ✅\n\n"
        f"ನಿಮ್ಮ {req.crop} ({req.area_acres} ಎಕರೆ) ದಾಖಲಾಗಿದೆ.\n\n"
        f"📍 {req.district}:\n"
        f"{sat['emoji']} {req.crop} saturation: {sat['saturation_pct']:.0f}% "
        f"({sat['risk_level']} RISK)\n{sat['risk_kannada']}\n\n— KisanMitra 🌾"
    )
    return {
        "success":        True,
        "declaration_id": declaration.id,
        "saturation":     sat,
        "whatsapp_reply": reply,
    }


@router.get("/saturation/{district}/{crop}")
async def get_saturation(
    district: str,
    crop: str,
    season: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    from backend.schemas import _derive_season
    return await farmer_service.calc_saturation(district, crop, season or _derive_season(), db)


@router.get("/api/v1/farmers/{phone}/declarations")
async def farmer_declarations(
    phone: str,
    caller_id: str,
    x_internal_secret: str | None = Header(None, alias="X-Internal-Secret"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Returns a farmer's own crop declarations, ordered newest first.

    `phone`             — the farmer's sender_id as stored in crop_declarations.phone
    `caller_id`        — the requesting sender's identity (required query param).
    `X-Internal-Secret` — bot-to-backend authentication header.

    Authorization:
    1. X-Internal-Secret MUST match settings.secret_key (prevents direct external queries).
    2. caller_id MUST match phone (prevents cross-user IDOR access).
    """
    if not x_internal_secret or x_internal_secret != settings.secret_key:
        logger.warning(
            "Unauthorized client attempt on farmer_declarations: missing/invalid X-Internal-Secret."
        )
        raise HTTPException(status_code=401, detail="Unauthorized client.")

    if caller_id != phone:
        logger.warning(
            "IDOR attempt blocked: caller_id=%r tried to read phone=%r declarations.",
            caller_id, phone,
        )
        raise HTTPException(status_code=403, detail="Access denied.")

    result = await db.execute(
        select(CropDeclaration)
        .where(CropDeclaration.phone == phone)
        .order_by(CropDeclaration.declared_at.desc())
    )
    decls = result.scalars().all()
    return {
        "phone": phone,
        "count": len(decls),
        "declarations": [
            {
                "id":          d.id,
                "crop":        d.crop,
                "district":    d.district,
                "area_acres":  d.area_acres,
                "season":      d.season,
                "declared_at": d.declared_at.isoformat() if d.declared_at else None,
            }
            for d in decls
        ],
    }

@router.get("/declarations/summary")
async def summary(db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(select(CropDeclaration))
    decls  = result.scalars().all()
    
    # Master lists for dropdowns to ensure all 31 districts and major crops appear even if no survey data exists yet.
    master_districts = [
        "Bagalkot", "Ballari", "Belagavi", "Bengaluru Rural", "Bengaluru Urban",
        "Bidar", "Chamarajanagar", "Chikkaballapur", "Chikkamagaluru", "Chitradurga",
        "Dakshina Kannada", "Davanagere", "Dharwad", "Gadag", "Hassan", "Haveri",
        "Kalaburagi", "Kodagu", "Kolar", "Koppal", "Mandya", "Mysuru", "Raichur",
        "Ramanagara", "Shivamogga", "Tumakuru", "Udupi", "Uttara Kannada",
        "Vijayapura", "Yadgir", "Vijayanagara"
    ]
    
    # The 33 normalized crops + Paddy + Wheat for terminal completeness
    master_crops = [
        'Arecanut', 'Avarekai', 'Brinjal', 'Cabbage', 'Capsicum', 'Chrysanthemum', 
        'Coriander', 'Cotton', 'Cowpea', 'Grapes', 'Green Chilli', 'Green Gram', 
        'Groundnut', 'Lemon', 'Maize', 'Mango', 'Marigold', 'Mixed Crops', 'Onion', 
        'Others', 'Paddy', 'Pomegranate', 'Potato', 'Ragi', 'Rose', 'Sapota', 
        'Sericulture', 'Soybean', 'Sugarcane', 'Sweet Corn', 'Tobacco', 'Tomato', 
        'Toor Dal', 'Turmeric', 'Wheat'
    ]

    if not decls:
        return {
            "total_declarations": 0,
            "total_farmers": 0,
            "districts": master_districts,
            "crops": {c: 0 for c in master_crops},
            "active_pairs": [],
            "message": "No declarations yet."
        }
    df = pd.DataFrame([{
        "phone":    d.phone,
        "district": d.district,
        "crop":     d.crop,
    } for d in decls])
    
    # Merge actual DB counts into master list dictionary for frontend chart support
    crop_counts = df["crop"].value_counts().to_dict()
    final_crops = {c: crop_counts.get(c, 0) for c in master_crops}
    
    # Get unique active district-crop pairs
    active_pairs = df[["district", "crop"]].drop_duplicates().to_dict("records")

    return {
        "total_declarations": len(df),
        "total_farmers":      int(df["phone"].nunique()),
        "districts":          master_districts,
        "crops":              final_crops,
        "active_pairs":       active_pairs,
    }


@router.get("/declarations")
async def get_declarations(
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
) -> list:
    result = await db.execute(
        select(CropDeclaration)
        .order_by(CropDeclaration.declared_at.desc())
        .limit(limit)
    )
    decls = result.scalars().all()
    return [
        {
            "id": d.id,
            "farmer_name": d.farmer_name,
            "phone": d.phone,
            "village": d.village,
            "district": d.district,
            "taluk": d.taluk,
            "crop": d.crop,
            "area_acres": d.area_acres,
            "season": d.season,
            "trust_score": d.trust_score,
            "satellite_status": d.satellite_status,
            "declared_at": d.declared_at.isoformat() if d.declared_at else None,
        }
        for d in decls
    ]


@router.post("/farmer/advisory")
async def get_advisory(
    req: dict,
    db: AsyncSession = Depends(get_db),
) -> dict:
    query = req.get("query", "")
    crop = req.get("crop", None)
    if not query:
        raise HTTPException(400, "Query cannot be empty.")
    from backend.services.rag import get_agronomy_advice
    response = await get_agronomy_advice(query, db, crop)

    # Persist web query and response to ChatHistory for RAG telemetry
    user_log = ChatHistory(
        phone_number="WebFarmer",
        role="user",
        message_content=query,
        intent_category="AGRONOMY_ADVICE"
    )
    assistant_log = ChatHistory(
        phone_number="WebFarmer",
        role="assistant",
        message_content=response,
        intent_category="AGRONOMY_ADVICE"
    )
    db.add(user_log)
    db.add(assistant_log)
    try:
        await db.commit()
        await db.refresh(assistant_log)
    except Exception as commit_ex:
        logger.error(f"DB COMMIT FAILED in get_advisory: {commit_ex}")
        await db.rollback()

    return {"response": response, "id": str(assistant_log.id)}


@router.post("/farmer/advisory/feedback")
async def get_advisory_feedback(
    req: dict,
    db: AsyncSession = Depends(get_db),
) -> dict:
    message_id = req.get("message_id")
    score = req.get("score")
    if score not in [1, -1]:
        raise HTTPException(400, "Invalid feedback score. Must be 1 or -1.")
    try:
        uuid_id = UUID(message_id)
    except ValueError:
        raise HTTPException(400, "Invalid message UUID format.")

    stmt = select(ChatHistory).where(ChatHistory.id == uuid_id, ChatHistory.role == "assistant")
    res = await db.execute(stmt)
    log_entry = res.scalar_one_or_none()
    if not log_entry:
        raise HTTPException(404, "Advisory log entry not found.")

    log_entry.feedback_score = score
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(500, "Could not save feedback to database.")

    return {"success": True}



@router.post("/farmer/declaration/{id}/verify")
async def verify_declaration(
    id: int,
    req: dict,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
) -> dict:
    status = req.get("status")
    if status not in ["verified", "failed", "pending"]:
        raise HTTPException(400, "Invalid status.")
    
    result = await db.execute(select(CropDeclaration).where(CropDeclaration.id == id))
    d = result.scalar_one_or_none()
    if not d:
        raise HTTPException(404, "Declaration not found.")
    
    d.satellite_status = status
    if status == "verified":
        d.trust_score = 1.0
    elif status == "failed":
        d.trust_score = 0.0
    
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(500, "Database update error.")
    
    return {"success": True, "id": id, "satellite_status": status, "trust_score": d.trust_score}


@router.delete("/farmer/declaration/{id}")
async def delete_declaration(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
) -> dict:
    result = await db.execute(select(CropDeclaration).where(CropDeclaration.id == id))
    d = result.scalar_one_or_none()
    if not d:
        raise HTTPException(404, "Declaration entry not found.")

    await db.delete(d)
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(500, f"Database deletion error: {exc}")

    return {"success": True, "id": id, "message": "Declaration deleted successfully from database."}

