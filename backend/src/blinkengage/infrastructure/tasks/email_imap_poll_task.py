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

from blinkengage.application.brain.source_ingestion import (
    KnowledgeSourceIngestionService,
)
from blinkengage.application.services.inbound_message_events import (
    publish_inbound_message_events,
)
from blinkengage.core.celery_app import celery_app
from blinkengage.core.config import Settings, get_settings
from blinkengage.core.logging import get_logger
from blinkengage.domain.brain.ingestion import ChannelPurpose, parse_channel_purpose
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
) -> list[tuple[bytes, bytes]]:
    """Runs on a worker thread — ``imaplib`` is synchronous, the same
    "wrap the sync client" pattern ``AttachmentStore`` already established
    for ``minio``.

    **Fetches without marking anything.** This used to set ``\\Seen`` inside
    this loop and call that the idempotency mechanism, which meant a crash
    between reading a message and persisting it lost the message permanently,
    with nothing anywhere recording that it had existed. For a customer that
    costs a resend; for a knowledge mailbox it is a price list that silently
    never arrived.

    The flag is now applied by :func:`_mark_seen_sync` *after* the message has
    been persisted, so it is an optimisation rather than the system of record.
    Redelivery is safe in both directions: knowledge mail is caught by the
    unique constraint on ``knowledge_source_messages``, and customer mail by
    the existing ``(channel_config_id, external_message_id)`` lookup and its
    partial unique index on ``messages``.

    Returns ``(uid, raw)`` pairs so the caller can acknowledge precisely the
    messages it managed to store.
    """
    imap_cls = imaplib.IMAP4_SSL if use_ssl else imaplib.IMAP4
    connection = imap_cls(host, port)
    try:
        connection.login(username, password)
        connection.select(folder)
        status, data = connection.search(None, "UNSEEN")
        if status != "OK" or not data or not data[0]:
            return []
        fetched: list[tuple[bytes, bytes]] = []
        for uid in data[0].split():
            fetch_status, fetch_data = connection.fetch(uid, "(RFC822)")
            if fetch_status == "OK" and fetch_data and isinstance(fetch_data[0], tuple):
                fetched.append((uid, fetch_data[0][1]))
        return fetched
    finally:
        with contextlib.suppress(imaplib.IMAP4.error):
            connection.close()
        connection.logout()


def _mark_seen_sync(
    host: str,
    port: int,
    username: str,
    password: str,
    use_ssl: bool,
    folder: str,
    uids: list[bytes],
) -> None:
    """Acknowledge messages that are already durably stored.

    Best-effort by design: failing to set the flag costs one redelivery, which
    both pipelines already recognise. Failing to *store* costs the message,
    which is why the order is this way round and not the other.
    """
    if not uids:
        return
    imap_cls = imaplib.IMAP4_SSL if use_ssl else imaplib.IMAP4
    connection = imap_cls(host, port)
    try:
        connection.login(username, password)
        connection.select(folder)
        for uid in uids:
            with contextlib.suppress(imaplib.IMAP4.error):
                # ``search`` returns byte sequence numbers; ``store`` is typed
                # for the str form and accepts either at runtime.
                connection.store(uid.decode(), "+FLAGS", "\\Seen")
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

    port = int(credentials.get("imap_port", 993))
    username = credentials.get("imap_username", "")
    password = credentials.get("imap_password", "")
    use_ssl = bool(credentials.get("imap_use_ssl", True))
    folder = credentials.get("imap_folder", "INBOX")

    fetched = await to_thread.run_sync(
        _fetch_unseen_sync, host, port, username, password, use_ssl, folder
    )
    if not fetched:
        return 0

    events = OutboxEventPublisher(EventOutboxRepository(session))
    # The branch, and it happens *before* anything parses the message into an
    # InboundMessage. Deliberately earlier than it strictly has to be: the
    # provider's parser uploads every attachment to object storage on its way
    # through, which is the extraction step Phase 4C excludes, and it discards
    # the Authentication-Results headers sender authorization needs.
    purpose = parse_channel_purpose(config.purpose)
    ingested = 0
    acknowledged: list[bytes] = []

    if purpose is ChannelPurpose.KNOWLEDGE_INGESTION:
        ingestion = KnowledgeSourceIngestionService(session=session, events=events)
        for uid, raw in fetched:
            outcome = await ingestion.ingest(config=config, raw=raw)
            # A duplicate is acknowledged too: the row already exists, so
            # re-reading it forever would be the only alternative.
            if outcome.stored or outcome.duplicate:
                acknowledged.append(uid)
            if outcome.accepted:
                ingested += 1
    elif purpose is ChannelPurpose.CUSTOMER_SUPPORT:
        provider = factory.build(config)
        for uid, raw in fetched:
            messages = await provider.receive_message(raw)
            await publish_inbound_message_events(events, config=config, messages=messages)
            acknowledged.append(uid)
            ingested += len(messages)
    else:
        # OTHER, or anything a future build adds. Routed nowhere and left
        # unread, so the mail is still there when somebody decides what it is
        # for. Guessing would mean picking one of the two pipelines.
        logger.warning(
            "email_poll_unroutable_purpose",
            channel_config_id=str(config.id),
            purpose=purpose.value,
        )
        return 0

    # Only now, and only for what is durably stored. The session is committed
    # by the caller's `session_scope` before this coroutine's caller returns;
    # marking here rather than inside the loop keeps the flag strictly behind
    # persistence even if the connection drops mid-batch.
    await session.flush()
    await to_thread.run_sync(
        _mark_seen_sync, host, port, username, password, use_ssl, folder, acknowledged
    )
    return ingested


async def _poll_all_email_channels_async() -> int:
    settings = get_settings()
    session_factory = _get_session_factory(settings)
    factory = _get_provider_factory(settings)

    try:
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
    finally:
        # See infrastructure/events/relay.py's identical fix for why this
        # is required: a pooled asyncpg connection is bound to the event
        # loop that opened it, but this task's cached engine/session
        # factory outlive any single `asyncio.run()`-created loop —
        # without disposing the pool here, the *next* invocation's loop
        # would try to reuse a connection from *this* loop and crash.
        if _engine is not None:
            await _engine.dispose()


@celery_app.task(name="blinkengage.channels.poll_email_imap")  # type: ignore[misc]
def poll_email_imap() -> int:
    return asyncio.run(_poll_all_email_channels_async())
