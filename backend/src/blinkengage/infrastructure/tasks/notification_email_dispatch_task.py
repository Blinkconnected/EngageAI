"""Celery-beat-scheduled email dispatch for notifications. See
``docs/architecture/notifications.md``.

Uses the platform's own SMTP settings (``settings.smtp_*``), never a
company's per-channel ``EmailProvider`` credentials — a notification must
reach an agent even for a company that has configured no customer-facing
email channel at all. Same sync-Celery-task-wrapping-an-async-service
bridge pattern ``sla_sweep_task.py`` already established, and the same
"claim undispatched rows, mark them, no separate cursor table" idempotency
shape as the outbox relay / IMAP poll.
"""

import asyncio
from datetime import UTC, datetime
from email.message import EmailMessage

import aiosmtplib
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from blinkengage.core.celery_app import celery_app
from blinkengage.core.config import Settings, get_settings
from blinkengage.core.logging import get_logger
from blinkengage.domain.notification_types import NotificationChannel
from blinkengage.infrastructure.database.models.notification import Notification
from blinkengage.infrastructure.database.models.user import User
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)
from blinkengage.infrastructure.repositories.notification_preference_repository import (
    NotificationPreferenceRepository,
)

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None

_BATCH_SIZE = 50


def _get_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _session_factory is None:
        _engine = create_engine(settings)
        _session_factory = create_session_factory(_engine)
    return _session_factory


async def _send_one(settings: Settings, *, to_address: str, notification: Notification) -> None:
    message = EmailMessage()
    message["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_address}>"
    message["To"] = to_address
    message["Subject"] = notification.title
    message.set_content(notification.body)

    await aiosmtplib.send(
        message,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        use_tls=settings.smtp_use_tls,
    )


async def dispatch_pending(session: AsyncSession, settings: Settings) -> int:
    """The testable core — takes an external session, unlike the Celery
    task wrapper below (which builds its own engine/session and can't be
    pointed at a test database). Mirrors ``email_imap_poll_task.py``'s
    ``poll_channel_config`` split for the same reason."""
    dispatched = 0

    result = await session.execute(
        select(Notification)
        .where(Notification.email_dispatched_at.is_(None))
        .order_by(Notification.created_at)
        .limit(_BATCH_SIZE)
    )
    pending = list(result.scalars().all())

    preferences = NotificationPreferenceRepository(session)
    for notification in pending:
        user = await session.get(User, notification.user_id)
        if user is None or not user.email:
            notification.email_dispatched_at = datetime.now(UTC)
            continue
        preference = await preferences.get(
            user_id=notification.user_id,
            notification_type=notification.notification_type,
            channel=NotificationChannel.EMAIL,
        )
        if preference is not None and not preference.enabled:
            # The user opted out of email for this notification type —
            # "dispatched" means "we decided what to do with it," not
            # necessarily "we sent an email," so this still marks the row
            # rather than leaving it to be re-checked every sweep forever.
            notification.email_dispatched_at = datetime.now(UTC)
            continue
        try:
            await _send_one(settings, to_address=user.email, notification=notification)
        except Exception:
            # One recipient's mailbox/SMTP failure must not block the
            # rest of the batch — left undispatched, retried next sweep.
            logger.warning(
                "notification_email_dispatch_failed",
                notification_id=str(notification.id),
                exc_info=True,
            )
            continue
        notification.email_dispatched_at = datetime.now(UTC)
        dispatched += 1

    if dispatched:
        logger.info("notification_emails_dispatched", count=dispatched)
    return dispatched


async def _dispatch_pending_async() -> int:
    settings = get_settings()
    session_factory = _get_session_factory(settings)
    try:
        async with session_scope(session_factory) as session:
            return await dispatch_pending(session, settings)
    finally:
        # See infrastructure/events/relay.py's identical fix for why this
        # is required: a pooled asyncpg connection is bound to the event
        # loop that opened it, but this task's cached engine/session
        # factory outlive any single `asyncio.run()`-created loop —
        # without disposing the pool here, the *next* invocation's loop
        # would try to reuse a connection from *this* loop and crash.
        if _engine is not None:
            await _engine.dispose()


@celery_app.task(name="blinkengage.notifications.dispatch_pending_emails")  # type: ignore[misc]
def dispatch_pending_emails() -> int:
    return asyncio.run(_dispatch_pending_async())
