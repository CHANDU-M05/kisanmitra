# pyrefly: ignore [missing-import]
from fastapi import APIRouter

from .prices import router as prices_router
from .farmers import router as farmers_router
from .system import router as system_router
from .webhook import router as webhook_router
from .analytics import router as analytics_router
from .auth import router as auth_router
from .audit import router as audit_router
from .conversation import router as conversation_router

api_router = APIRouter()
api_router.include_router(prices_router)
api_router.include_router(farmers_router)
api_router.include_router(system_router)
api_router.include_router(webhook_router)
api_router.include_router(analytics_router)
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(audit_router)
api_router.include_router(conversation_router)
