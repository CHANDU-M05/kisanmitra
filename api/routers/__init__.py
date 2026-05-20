from fastapi import APIRouter

from .prices import router as prices_router
from .farmers import router as farmers_router
from .satellite import router as satellite_router
from .system import router as system_router
from .webhook import router as webhook_router
from .analytics import router as analytics_router

api_router = APIRouter()
api_router.include_router(prices_router)
api_router.include_router(farmers_router)
api_router.include_router(satellite_router)
api_router.include_router(system_router)
api_router.include_router(webhook_router)
api_router.include_router(analytics_router)
