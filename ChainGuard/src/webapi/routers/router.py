from fastapi import APIRouter

from . import auth, business, imports_settings

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(business.router)
api_router.include_router(imports_settings.router)

