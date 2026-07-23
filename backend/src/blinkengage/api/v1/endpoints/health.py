"""Liveness and readiness probes for orchestration/monitoring."""

import asyncio
from typing import Annotated

import aio_pika
from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.api.deps import get_db_session, get_redis, get_settings_dep
from blinkengage.core.config import Settings

router = APIRouter(tags=["health"])

_DEPENDENCY_CHECK_TIMEOUT_SECONDS = 3


class HealthStatus(BaseModel):
    status: str
    service: str = "blinkengage-api"


class ReadinessStatus(BaseModel):
    status: str
    database: str
    redis: str
    rabbitmq: str


@router.get("/health", response_model=HealthStatus)
async def liveness() -> HealthStatus:
    """Process is up. Does not check downstream dependencies."""
    return HealthStatus(status="ok")


async def _check_rabbitmq(settings: Settings) -> str:
    try:
        connection = await asyncio.wait_for(
            aio_pika.connect(settings.rabbitmq_url), timeout=_DEPENDENCY_CHECK_TIMEOUT_SECONDS
        )
        await connection.close()
    except Exception:  # any failure here means "not ready", not a 500
        return "unreachable"
    return "ok"


@router.get("/health/ready", response_model=ReadinessStatus)
async def readiness(
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> ReadinessStatus:
    """Process is up AND every critical dependency (database, cache,
    message broker) is reachable — the check a load-balanced pool's
    orchestrator/load balancer should use to decide whether to route
    traffic to this replica, not just whether the process is alive."""
    database_status = "ok"
    try:
        await session.execute(text("SELECT 1"))
    except Exception:  # any failure here means "not ready", not a 500
        database_status = "unreachable"

    redis_status = "ok"
    try:
        await asyncio.wait_for(redis.ping(), timeout=_DEPENDENCY_CHECK_TIMEOUT_SECONDS)
    except Exception:  # any failure here means "not ready", not a 500
        redis_status = "unreachable"

    rabbitmq_status = await _check_rabbitmq(settings)

    all_ok = database_status == redis_status == rabbitmq_status == "ok"
    if not all_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessStatus(
        status="ok" if all_ok else "degraded",
        database=database_status,
        redis=redis_status,
        rabbitmq=rabbitmq_status,
    )
