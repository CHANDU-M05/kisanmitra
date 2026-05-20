from fastapi import APIRouter, Depends, HTTPException
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.models import CropDeclaration
from api.schemas import DeclareRequest
from api.services import farmer_service

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
    season: str = "kharif_2025",
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await farmer_service.calc_saturation(district, crop, season, db)


@router.get("/declarations/summary")
async def summary(db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(select(CropDeclaration))
    decls  = result.scalars().all()
    if not decls:
        return {"message": "No declarations yet.", "tip": "Collect data during Ugadi!"}
    df = pd.DataFrame([{
        "phone":    d.phone,
        "district": d.district,
        "crop":     d.crop,
    } for d in decls])
    return {
        "total_declarations": len(df),
        "total_farmers":      int(df["phone"].nunique()),
        "districts":          df["district"].unique().tolist(),
        "crops":              df["crop"].value_counts().to_dict(),
    }
