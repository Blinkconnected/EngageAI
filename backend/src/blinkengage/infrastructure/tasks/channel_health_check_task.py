"""Celery-beat-scheduled channel health monitoring — Phase 1: Channel
Experience. Runs ``ChannelProvider.health_check()`` for every active
channel across every company and records the *latest* status onto
``ChannelConfig`` (for an O(1) badge on the channel list) plus a
``ChannelConnectionLog`` row, but only on a status **transition**
(healthy -> unhealthy or back) — not on every tick, which would drown a
real incident's signal in thousands of routine "still healthy" rows over
time. See ``docs/architecture/channel-integration-spec.md``.

Structured the same way as ``email_imap_poll_task.py``: its own
module-level cached engine/session-factory/redis/minio, disposed at the
end of each run since the cached asyncpg pool is bound to the event loop
that created it and this task's loop is recreated on every invocation.
"""

import asyncio
from datetime import UTC, datetime

from minio import Minio
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from blinkengage.core.celery_app import celery_app
from blinkengage.core.config import Settings, get_settings
from blinkengage.core.logging import get_logger
from blinkengage.infrastructure.cache.redis import create_redis_client
from blinkengage.infrastructure.channels.error_sanitizer import (
    redact_credentials,
    safe_health_check,
)
from blinkengage.infrastructure.channels.factory import ChannelProviderFactory
from blinkengage.infrastructure.database.models.channel_config import ChannelConfig
from blinkengage.infrastructure.database.models.channel_connection_log import (
    ChannelConnectionLog,
)
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)
from blinkengage.infrastructure.events.realtime_publisher import RealtimePublisher
from blinkengage.infrastructure.storage.attachment_store import AttachmentStore
from blinkengage.infrastructure.storage.s3_client import create_minio_client

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_redis: Redis | None = None
_minio_client: Minio | None = None


def _get_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _session_factory is None:
        _engine = create_engine(settings)
        _session_factory = create_session_factory(_engine)
    return _session_factory


def _get_provider_factory(settings: Settings) -> ChannelProviderFactory:
    global _redis, _minio_client
    if _redis is None:
        _redis = create_redis_client(settings)
    if _minio_client is None:
        _minio_client = create_minio_client(settings)
    attachments = AttachmentStore(_minio_client, bucket=settings.s3_bucket_attachments)
    return ChannelProviderFactory(realtime=RealtimePublisher(_redis), attachments=attachments)


async def check_channel(
    config: ChannelConfig, *, session: AsyncSession, factory: ChannelProviderFactory
) -> bool:
    """Returns whether a connection-log row was written (a status
    transition happened) — purely for the task's return-value summary."""
    provider = factory.build(config)
    # Not a raw provider.health_check() call: every current provider's own
    # implementation already catches its library's ordinary HTTP error
    # internally and returns the failure detail directly (never raises),
    # so this sweep — which persists that detail onto ChannelConfig and a
    # ChannelConnectionLog row any `channels.read` principal can read —
    # needs the same credential redaction Test Connection gets via
    # safe_health_check(), not just a try/except around this call.
    result = await safe_health_check(provider, config.credentials)
    new_status = "healthy" if result.healthy else "unhealthy"
    transitioned = config.last_health_status is not None and config.last_health_status != new_status
    first_check = config.last_health_status is None

    config.last_health_status = new_status
    config.last_health_checked_at = datetime.now(UTC)
    config.last_health_detail = result.detail

    if first_check:
        event_type = "health_check_initial"
    elif transitioned:
        event_type = "health_check_recovered" if result.healthy else "health_check_became_unhealthy"
    else:
        event_type = None

    if event_type is not None:
        session.add(
            ChannelConnectionLog(
                channel_config_id=config.id,
                company_id=config.company_id,
                event_type=event_type,
                level="info" if result.healthy else "error",
                message=result.detail
                or ("Connection healthy." if result.healthy else "Connection unhealthy."),
            )
        )
        return True
    return False


async def _check_all_channels_async() -> dict[str, int]:
    settings = get_settings()
    session_factory = _get_session_factory(settings)
    factory = _get_provider_factory(settings)

    try:
        async with session_scope(session_factory) as session:
            result = await session.execute(
                select(ChannelConfig).where(
                    ChannelConfig.is_active.is_(True), ChannelConfig.deleted_at.is_(None)
                )
            )
            configs = list(result.scalars().all())

            checked = 0
            transitions = 0
            for config in configs:
                try:
                    if await check_channel(config, session=session, factory=factory):
                        transitions += 1
                    checked += 1
                except Exception as exc:  # noqa: BLE001 - one channel's failure shouldn't stop the sweep
                    logger.warning(
                        "channel_health_check_errored",
                        channel_config_id=str(config.id),
                        error=redact_credentials(str(exc), config.credentials),
                    )
            if transitions:
                logger.info(
                    "channel_health_check_transitions", checked=checked, transitions=transitions
                )
            return {"checked": checked, "transitions": transitions}
    finally:
        # See infrastructure/events/relay.py's identical fix: a pooled
        # asyncpg connection is bound to the event loop that opened it,
        # but this task's cached engine/session factory outlive any
        # single asyncio.run()-created loop.
        if _engine is not None:
            await _engine.dispose()


@celery_app.task(name="blinkengage.channels.check_channel_health")  # type: ignore[misc]
def check_channel_health() -> dict[str, int]:
    return asyncio.run(_check_all_channels_async())
