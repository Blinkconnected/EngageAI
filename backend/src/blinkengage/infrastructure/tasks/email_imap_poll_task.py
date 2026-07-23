"""Celery-beat-scheduled IMAP inbound poll — the "IMAP" half of the Email
channel (SMTP handles outbound; a webhook-capable ESP uses the generic
``POST /webhooks/{channel_config_id}`` route instead of this poll). See
``docs/architecture/email-channel.md``.
"""

import asyncio
import contextlib
import imaplib

from anyio import to_thread
from minio import Minio
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from blinkengage.application.services.inbound_message_events import (
    publish_inbound_message_events,
)
from blinkengage.core.celery_app import celery_app
from blinkengage.core.config import Settings, get_settings
from blinkengage.core.logging import get_logger
from blinkengage.infrastructure.cache.redis import create_redis_client
from blinkengage.infrastructure.channels.factory import ChannelProviderFactory
from blinkengage.infrastructure.database.models.channel_config import ChannelConfig
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)
from blinkengage.infrastructure.events.outbox_publisher import OutboxEventPublisher
from blinkengage.infrastructure.events.realtime_publisher import RealtimePublisher
from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
)
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


def _fetch_unseen_sync(
    host: str, port: int, username: str, password: str, use_ssl: bool, folder: str
) -> list[bytes]:
    """Runs on a worker thread — ``imaplib`` is synchronous, the same
    "wrap the sync client" pattern ``AttachmentStore`` already established
    for ``minio``. Marking each fetched message ``\\Seen`` as it's read is
    the idempotency mechanism: a message is never fetched twice, no
    separate cursor table needed."""
    imap_cls = imaplib.IMAP4_SSL if use_ssl else imaplib.IMAP4
    connection = imap_cls(host, port)
    try:
        connection.login(username, password)
        connection.select(folder)
        status, data = connection.search(None, "UNSEEN")
        if status != "OK" or not data or not data[0]:
            return []
        raw_messages: list[bytes] = []
        for uid in data[0].split():
            fetch_status, fetch_data = connection.fetch(uid, "(RFC822)")
            if fetch_status == "OK" and fetch_data and isinstance(fetch_data[0], tuple):
                raw_messages.append(fetch_data[0][1])
                connection.store(uid, "+FLAGS", "\\Seen")
        return raw_messages
    finally:
        with contextlib.suppress(imaplib.IMAP4.error):
            connection.close()
        connection.logout()


async def poll_channel_config(
    config: ChannelConfig, *, session: AsyncSession, factory: ChannelProviderFactory
) -> int:
    credentials = config.credentials
    host = credentials.get("imap_host")
    if not host:
        return 0

    raw_messages = await to_thread.run_sync(
        _fetch_unseen_sync,
        host,
        int(credentials.get("imap_port", 993)),
        credentials.get("imap_username", ""),
        credentials.get("imap_password", ""),
        bool(credentials.get("imap_use_ssl", True)),
        credentials.get("imap_folder", "INBOX"),
    )
    if not raw_messages:
        return 0

    provider = factory.build(config)
    events = OutboxEventPublisher(EventOutboxRepository(session))
    ingested = 0
    for raw in raw_messages:
        messages = await provider.receive_message(raw)
        await publish_inbound_message_events(events, config=config, messages=messages)
        ingested += len(messages)
    return ingested


async def _poll_all_email_channels_async() -> int:
    settings = get_settings()
    session_factory = _get_session_factory(settings)
    factory = _get_provider_factory(settings)

    async with session_scope(session_factory) as session:
        result = await session.execute(
            select(ChannelConfig).where(
                ChannelConfig.channel_type == "email",
                ChannelConfig.is_active.is_(True),
                ChannelConfig.deleted_at.is_(None),
            )
        )
        configs = list(result.scalars().all())

        total = 0
        for config in configs:
            total += await poll_channel_config(config, session=session, factory=factory)
        if total:
            logger.info("email_imap_poll_ingested", count=total)
        return total


@celery_app.task(name="blinkengage.channels.poll_email_imap")  # type: ignore[misc]
def poll_email_imap() -> int:
    return asyncio.run(_poll_all_email_channels_async())
