from fastapi import APIRouter

from blinkengage.api.v1.endpoints import (
    agents,
    audit_logs,
    auth,
    customers,
    departments,
    health,
    teams,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(departments.router)
api_router.include_router(teams.router)
api_router.include_router(agents.router)
api_router.include_router(customers.router)
api_router.include_router(audit_logs.router)
