from fastapi import APIRouter

from blinkengage.api.v1.endpoints import health

api_router = APIRouter()
api_router.include_router(health.router)
