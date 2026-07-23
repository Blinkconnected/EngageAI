"""FastAPI application factory.

Uvicorn entrypoint: ``blinkengage.main:app``.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from blinkengage.api.v1.router import api_router
from blinkengage.core.config import get_settings
from blinkengage.core.container import Container
from blinkengage.core.exceptions import register_exception_handlers
from blinkengage.core.logging import configure_logging, get_logger
from blinkengage.core.security_headers import SecurityHeadersMiddleware

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    logger.info("application_starting", environment=app.state.container.settings().environment)
    yield
    engine = app.state.container.engine()
    await engine.dispose()
    redis = app.state.container.redis()
    await redis.aclose()
    logger.info("application_stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    app = FastAPI(
        title=settings.app_name,
        description="Enterprise AI Powered Omnichannel Customer Engagement Platform API",
        version="0.1.0",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
        lifespan=lifespan,
    )

    container = Container()
    app.state.container = container

    # Fails fast at startup, not at request time: allow_credentials=True
    # (needed so a browser client can send its Authorization header)
    # combined with a wildcard origin would let any website read
    # authenticated responses on a victim's behalf — the browser spec
    # actually forbids this combination and a wildcard is silently
    # ignored with credentialed requests, which is worse than an error,
    # since it looks configured but isn't. See docs/security/hardening.md.
    if "*" in settings.cors_allow_origins:
        raise ValueError(
            "cors_allow_origins must not contain '*' — allow_credentials=True requires an "
            "explicit origin allowlist"
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(SecurityHeadersMiddleware, settings=settings)

    register_exception_handlers(app)

    app.include_router(api_router, prefix=settings.api_v1_prefix)

    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    return app


app = create_app()
