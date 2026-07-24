from fastapi import APIRouter

from . import auth, business, imports_settings, v2

api_router = APIRouter(prefix="/api/v1")
api_v2_router = APIRouter(prefix="/api/v2")
api_router.include_router(auth.router)
api_router.include_router(business.router)
api_router.include_router(imports_settings.router)
api_v2_router.include_router(v2.router)
