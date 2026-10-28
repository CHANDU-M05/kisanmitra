from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from backend.core.database import get_db
from backend.core.models import AuditLog, AdminUser
from backend.routers.auth import get_current_user

router = APIRouter(prefix="/admin/audit-logs", tags=["audit"])


class AuditLogCreate(BaseModel):
    action: str
    target: str


@router.post("")
async def create_audit_log(
    payload: AuditLogCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user),
):
    client_ip = request.client.host if request.client else "127.0.0.1"
    log_entry = AuditLog(
        admin_username=current_user.username,
        action=payload.action,
        target=payload.target,
        ip_address=client_ip,
    )
    db.add(log_entry)
    await db.commit()
    await db.refresh(log_entry)
    return {
        "id": log_entry.id,
        "admin_username": log_entry.admin_username,
        "action": log_entry.action,
        "target": log_entry.target,
        "ip_address": log_entry.ip_address,
        "created_at": log_entry.created_at.isoformat() if log_entry.created_at else None,
    }


@router.get("")
async def list_audit_logs(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user),
):
    stmt = select(AuditLog).order_by(desc(AuditLog.created_at)).limit(limit)
    res = await db.execute(stmt)
    logs = res.scalars().all()
    return [
        {
            "id": log.id,
            "timestamp": log.created_at.isoformat() if log.created_at else "",
            "admin": log.admin_username,
            "action": log.action,
            "target": log.target,
            "ip": log.ip_address or "127.0.0.1",
        }
        for log in logs
    ]
