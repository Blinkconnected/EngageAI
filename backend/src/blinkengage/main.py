"""FastAPI application factory.

Uvicorn entrypoint: ``blinkengage.main:app``.
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import REGISTRY
from prometheus_fastapi_instrumentator import Instrumentator

from blinkengage.api.correlation_middleware import CorrelationIdMiddleware
from blinkengage.api.v1.router import api_router
from blinkengage.core.celery_app import celery_app
from blinkengage.core.changelog import ChangelogFormatError, current_release, load_releases
from blinkengage.core.config import get_settings
from blinkengage.core.container import Container
from blinkengage.core.correlation import CORRELATION_HEADER
from blinkengage.core.exceptions import register_exception_handlers
from blinkengage.core.logging import configure_logging, get_logger
from blinkengage.core.operational_metrics import (
    CACHE_SECONDS,
    OperationalCollector,
    register,
)
from blinkengage.core.security_headers import SecurityHeadersMiddleware
from blinkengage.core.wiring import verify_wiring

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    logger.info("application_starting", environment=app.state.container.settings().environment)

    # Keeps the operational gauges fresh off the scrape path. Started
    # here rather than from an @app.on_event("startup") hook because the
    # app already has a lifespan and mixing the two is deprecated.
    collector = app.state.operational_collector

    async def _refresh_operational_metrics() -> None:  # pragma: no cover - lifecycle
        while True:
            await collector.refresh(app.state.container.session_factory())
            await asyncio.sleep(CACHE_SECONDS)

    metrics_task = asyncio.create_task(_refresh_operational_metrics())

    yield

    # Cancelled and awaited, not just cancelled: leaving the task pending
    # makes the event loop complain on shutdown and can hold the session
    # open past the engine's disposal below.
    metrics_task.cancel()
    with suppress(asyncio.CancelledError):
        await metrics_task

    engine = app.state.container.engine()
    await engine.dispose()
    redis = app.state.container.redis()
    await redis.aclose()
    logger.info("application_stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    # Fails fast at startup, matching the CORS-wildcard fail-fast check
    # below: an app whose own version can't be determined is exactly as
    # misconfigured as one with an unusable CORS policy, and serving
    # traffic under a wrong/placeholder version silently would make
    # every downstream consumer of GET /api/v1/version (status pages,
    # support tooling, this very version-consistency tripwire test) trust
    # a lie. A missing/malformed CHANGELOG.md is only ever an operator
    # error, never a client-triggerable condition.
    current = current_release(load_releases(Path(settings.changelog_path)))
    if current is None:
        raise ChangelogFormatError(
            f"'{settings.changelog_path}' has no published release entries; "
            "the application version cannot be determined"
        )

    app = FastAPI(
        title=settings.app_name,
        description="Enterprise AI Powered Omnichannel Customer Engagement Platform API",
        version=current.version,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
        lifespan=lifespan,
    )

    container = Container()
    app.state.container = container

    # Refuses to boot with a critical collaborator missing. Four defects in
    # this codebase have had the same shape — a service that works alone,
    # reached through an optional dependency production never passed, failing
    # silently rather than loudly. See ``core/wiring.py`` for what each one
    # cost. Checked here, beside the version and CORS checks, for the same
    # reason: an application that would produce wrong business behaviour is
    # exactly as misconfigured as one with an unusable CORS policy.
    verify_wiring(container.session_factory())

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
        # `allow_headers` governs what a browser may *send*; a response
        # header is invisible to `fetch()` unless it is named here. The
        # billing console downloads its CSV export through the same
        # authenticated client as every other call, and reads the filename
        # to learn whether the file was truncated — which it cannot do if
        # the browser hides the header.
        expose_headers=[
            "Content-Disposition",
            "X-Export-Row-Cap",
            "X-Export-Row-Count",
            "X-Export-Total-Matched",
            "X-Export-Truncated",
            CORRELATION_HEADER,
        ],
    )
    app.add_middleware(SecurityHeadersMiddleware, settings=settings)
    # Outermost of the two, so every request — including one rejected by
    # a later middleware — still carries an id that its audit events and
    # log lines can be grouped by.
    app.add_middleware(CorrelationIdMiddleware)

    register_exception_handlers(app)

    app.include_router(api_router, prefix=settings.api_v1_prefix)

    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    # Two gauges the silent-failure alerts need — outbox backlog and
    # scheduler staleness. Refreshed on a timer rather than on the scrape
    # path, so a slow database cannot slow a scrape and a broken one
    # cannot fail it.
    # Only tasks the beat schedule actually declares, and each one's
    # interval — see the notes on OperationalCollector.__init__.
    intervals = {
        str(entry["task"]): float(entry["schedule"])
        for entry in celery_app.conf.beat_schedule.values()
        if isinstance(entry.get("schedule"), int | float)
    }
    collector = OperationalCollector(
        scheduled_tasks={entry["task"] for entry in celery_app.conf.beat_schedule.values()},
        expected_intervals=intervals,
    )
    register(REGISTRY, collector)
    app.state.operational_collector = collector

    return app


app = create_app()
