import asyncio
import json
import subprocess
import sys
import logging
from pathlib import Path
from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter(prefix="/satellite", tags=["satellite"])
BASE_DIR = Path(__file__).resolve().parents[2]
logger = logging.getLogger("kisanmitra.satellite")

class SatelliteRequest(BaseModel):
    lat: float
    lon: float
    crop: str = "Tomato"
    farmer_name: str = "Farmer"

def run_satellite_script(req: SatelliteRequest):
    """Background task to execute GEE script."""
    try:
        logger.info(f"Running satellite verification for {req.farmer_name}...")
        subprocess.run(
            [sys.executable, "scripts/04_satellite_verify.py",
             str(req.lat), str(req.lon), req.crop, req.farmer_name],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=120,
            check=True
        )
        logger.info(f"Verification complete for {req.farmer_name}")
    except Exception as e:
        logger.error(f"Satellite background task failed: {e}")

@router.post("/verify")
async def satellite_verify(req: SatelliteRequest, background_tasks: BackgroundTasks) -> JSONResponse:
    background_tasks.add_task(run_satellite_script, req)
    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "message": "Satellite verification initiated in background",
            "farmer": req.farmer_name
        }
    )
