"""Liveness and readiness probes for orchestration/monitoring."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.api.deps import get_db_session

router = APIRouter(tags=["health"])


class HealthStatus(BaseModel):
    status: str
    service: str = "blinkengage-api"


class ReadinessStatus(BaseModel):
    status: str
    database: str


@router.get("/health", response_model=HealthStatus)
async def liveness() -> HealthStatus:
    """Process is up. Does not check downstream dependencies."""
    return HealthStatus(status="ok")


@router.get("/health/ready", response_model=ReadinessStatus)
async def readiness(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ReadinessStatus:
    """Process is up AND its critical dependencies (database) are reachable."""
    await session.execute(text("SELECT 1"))
    return ReadinessStatus(status="ok", database="ok")
