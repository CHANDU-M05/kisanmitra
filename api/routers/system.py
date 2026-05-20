from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.models import CropDeclaration, MandiPrice
from api.services import ml_service

router = APIRouter(tags=["system"])

@router.get("/")
async def root() -> dict:
    return {
        "name":    "KisanMitra API",
        "version": "2.0.0",
        "db":      "PostgreSQL + PostGIS + pgvector",
        "model":   ml_service.MODEL is not None,
    }


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)) -> dict:
    result      = await db.execute(select(func.count()).select_from(CropDeclaration))
    decl_count  = result.scalar() or 0
    return {
        "status":       "healthy",
        "model_loaded": ml_service.MODEL is not None,
        "features":     len(ml_service.FEATURES),
        "declarations": decl_count,
        "time":         datetime.now().isoformat(),
    }


@router.get("/internal/status")
async def internal_status(db: AsyncSession = Depends(get_db)) -> dict:
    decl_count = (await db.execute(
        select(func.count()).select_from(CropDeclaration)
    )).scalar() or 0

    latest = (await db.execute(
        select(MandiPrice.arrival_date)
        .order_by(MandiPrice.arrival_date.desc())
        .limit(1)
    )).scalar_one_or_none()

    return {
        "model_loaded":      ml_service.MODEL is not None,
        "declaration_count": decl_count,
        "latest_price_date": latest.isoformat() if latest else None,
    }


@router.post("/internal/sync")
async def trigger_sync() -> dict:
    import asyncio
    import subprocess
    from pathlib import Path
    
    BASE_DIR = Path(__file__).resolve().parents[3]
    
    async def run_pipeline():
        loop = asyncio.get_event_loop()
        scripts = ["01_download_data.py", "02_clean_data.py", "03_train_model.py"]
        for script in scripts:
            await loop.run_in_executor(
                None,
                lambda s=script: subprocess.run(["python", f"scripts/{s}"], cwd=BASE_DIR)
            )
            
    import asyncio
    asyncio.create_task(run_pipeline())
    
    return {"status": "sync_started", "message": "AGMARKNET download and ML retraining triggered in background."}

