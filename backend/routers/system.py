from datetime import datetime
import io
import pypdf
from fastapi import APIRouter, Depends, BackgroundTasks, UploadFile, File, Form, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.models import CropDeclaration, MandiPrice, AdminUser, KnowledgeChunk
from backend.routers.auth import get_current_user
from backend.services import ml_service

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
    db_ok = False
    decl_count = 0
    latest_date_str = None
    try:
        result = await db.execute(select(func.count()).select_from(CropDeclaration))
        decl_count = result.scalar() or 0
        latest_res = await db.execute(select(func.max(MandiPrice.arrival_date)))
        max_date = latest_res.scalar()
        latest_date_str = max_date.isoformat() if max_date else None
        db_ok = True
    except Exception:
        db_ok = False

    model_ok = ml_service.MODEL is not None
    overall_healthy = db_ok and model_ok

    return {
        "status": "healthy" if overall_healthy else "degraded",
        "database_connected": db_ok,
        "model_loaded": model_ok,
        "features": len(ml_service.FEATURES) if model_ok else 0,
        "declarations": decl_count,
        "latest_price_date": latest_date_str,
        "timestamp": datetime.now().isoformat(),
    }


@router.get("/internal/status")
async def internal_status(
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
) -> dict:
    decl_count = (await db.execute(
        select(func.count()).select_from(CropDeclaration)
    )).scalar() or 0

    latest_date = (await db.execute(
        select(func.max(MandiPrice.arrival_date))
    )).scalar()

    return {
        "model_loaded":      ml_service.MODEL is not None,
        "declaration_count": decl_count,
        "latest_price_date": latest_date.isoformat() if latest_date else datetime.now().isoformat(),
    }


@router.post("/internal/sync")
async def trigger_sync(
    current_user: AdminUser = Depends(get_current_user)
) -> dict:
    import fcntl
    import os
    import asyncio
    import subprocess
    from pathlib import Path
    from fastapi import HTTPException
    
    BASE_DIR = Path(__file__).resolve().parents[3]
    LOCK_FILE = "/tmp/kisanmitra_sync.lock"
    
    # Try to acquire a non-blocking exclusive file lock.
    # This correctly synchronizes across all 4 Uvicorn worker processes.
    try:
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise HTTPException(status_code=409, detail="A synchronization job is already running.")
        
    async def run_pipeline():
        loop = asyncio.get_event_loop()
        scripts = ["01_download_data.py", "02_clean_data.py", "03_train_model.py"]
        try:
            for script in scripts:
                await loop.run_in_executor(
                    None,
                    lambda s=script: subprocess.run(["python", f"scripts/{s}"], cwd=BASE_DIR)
                )
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
            
    asyncio.create_task(run_pipeline())
    
    return {"status": "sync_started", "message": "AGMARKNET download and ML retraining triggered in background."}


@router.post("/internal/knowledge/upload")
async def upload_knowledge_document(
    file: UploadFile = File(...),
    crop: str = Form("All"),
    category: str = Form("General"),
    language: str = Form("kn"),
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
) -> dict:
    content = ""
    filename = file.filename or "unknown"
    
    # 1. Read document text
    if filename.endswith(".pdf"):
        try:
            pdf_bytes = await file.read()
            reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
            text_list = []
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    text_list.append(t)
            content = "\n".join(text_list)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to parse PDF document: {e}")
    else:
        # Fallback to UTF-8 text parsing
        try:
            file_bytes = await file.read()
            content = file_bytes.decode("utf-8")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to parse text document: {e}")
            
    if not content.strip():
        raise HTTPException(status_code=400, detail="Document content is empty.")
        
    # 2. Chunking
    # Split text into chunks of 500 characters, with 50 character overlap
    chunk_size = 500
    overlap = 50
    chunks = []
    start = 0
    while start < len(content):
        end = start + chunk_size
        chunks.append(content[start:end])
        start += (chunk_size - overlap)
        
    # 3. Generate embeddings and save to DB
    from backend.core.models import _HAS_PGVECTOR
    from backend.services.rag import embed_text
    
    inserted_count = 0
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
            
        vector = None
        if _HAS_PGVECTOR:
            vector = await embed_text(chunk)
            
        chunk_obj = KnowledgeChunk(
            crop=crop,
            category=category,
            content=chunk,
            embedding=vector,
            language=language,
            source=filename,
            districts=[],  # Default empty list for districts
            keywords=[]    # Default empty list for keywords
        )
        db.add(chunk_obj)
        inserted_count += 1
        
    await db.commit()
    
    return {
        "status": "success",
        "filename": filename,
        "chunks_created": inserted_count,
        "message": f"Successfully processed and embedded {inserted_count} text chunks into the RAG vector store."
    }


