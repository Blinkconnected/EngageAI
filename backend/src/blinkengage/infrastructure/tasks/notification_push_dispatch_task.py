"""Celery-beat-scheduled push dispatch for notifications. See
``docs/architecture/notifications.md``.

The sibling of ``notification_email_dispatch_task.py``, and deliberately
the same shape: claim ``Notification`` rows with no ``push_dispatched_at``,
consult the per-user preference, mark the row, and let a failure leave it
unmarked for the next sweep. Same sync-Celery-task-wrapping-an-async-
service bridge, same "no separate cursor table" idempotency.

Three things differ from email, each for a reason:

- **A stale window.** A push is an interruption claiming to be current, so
  anything older than ``settings.push_stale_after_minutes`` is marked
  without being sent. That single rule does three jobs: it stops
  forty-minute-late alerts, it bounds retries so a permanent failure
  cannot retry forever, and it means switching push on for the first time
  does not fire every historical notification at once.
- **Fan-out per recipient.** An email goes to one address; a push goes to
  every device the user has registered, and the outcomes can differ
  across them.
- **Dead tokens are deleted.** The provider is the only thing that knows a
  token is finished, and it says so exactly once per attempt.
"""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from blinkengage.core.celery_app import celery_app
from blinkengage.core.config import Settings, get_settings
from blinkengage.core.logging import get_logger
from blinkengage.domain.notification_types import NotificationChannel
from blinkengage.domain.push import PushMessage, PushOutcome, PushSender
from blinkengage.infrastructure.database.models.notification import Notification
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)
from blinkengage.infrastructure.push import build_push_sender
from blinkengage.infrastructure.repositories.device_token_repository import (
    DeviceTokenRepository,
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


async def _retire_stale(session: AsyncSession, *, cutoff: datetime) -> int:
    """Mark notifications too old to be worth pushing.

    Marked rather than left alone so the partial index on
    ``push_dispatched_at IS NULL`` stays small, and so the pending set
    never grows without bound on an installation that has push switched
    off at the preference level for everybody.
    """
    result = await session.execute(
        update(Notification)
        .where(
            Notification.push_dispatched_at.is_(None),
            Notification.created_at < cutoff,
        )
        .values(push_dispatched_at=datetime.now(UTC))
    )
    return int(result.rowcount or 0)


async def dispatch_pending(
    session: AsyncSession, settings: Settings, sender: PushSender
) -> int:
    """The testable core — takes an external session and an already-built
    sender, unlike the Celery wrapper below (which builds its own engine
    and cannot be pointed at a test database, and would otherwise need
    real credentials to exercise). Mirrors the email dispatcher's split
    for the same reason.

    Returns the number of notifications pushed to at least one device.
    """
    now = datetime.now(UTC)
    cutoff = now - timedelta(minutes=settings.push_stale_after_minutes)

    retired = await _retire_stale(session, cutoff=cutoff)
    if retired:
        logger.info("notification_pushes_skipped_stale", count=retired)

    result = await session.execute(
        select(Notification)
        .where(
            Notification.push_dispatched_at.is_(None),
            Notification.created_at >= cutoff,
        )
        .order_by(Notification.created_at)
        .limit(_BATCH_SIZE)
    )
    pending = list(result.scalars().all())
    if not pending:
        return 0

    devices = DeviceTokenRepository(session)
    preferences = NotificationPreferenceRepository(session)
    pushed = 0

    for notification in pending:
        preference = await preferences.get(
            user_id=notification.user_id,
            notification_type=notification.notification_type,
            channel=NotificationChannel.PUSH,
        )
        if preference is not None and not preference.enabled:
            # Opted out. "Dispatched" means "we decided what to do with
            # it", exactly as in the email sweep — so the row is marked
            # rather than re-examined every sweep forever.
            notification.push_dispatched_at = now
            continue

        registered = await devices.list_for_user(
            company_id=notification.company_id, user_id=notification.user_id
        )
        if not registered:
            notification.push_dispatched_at = now
            continue

        delivered_any = False
        retryable = False
        for device in registered:
            message = PushMessage(
                token=device.token,
                platform=device.platform,
                title=notification.title,
                body=notification.body,
                data=_deep_link_data(notification),
            )
            try:
                outcome = await sender.send(message)
            except Exception:
                # A sender is contracted not to raise for a provider
                # rejection, so reaching here means something genuinely
                # unexpected. Treated as retryable: dropping a
                # notification because of a bug in a transport is the
                # worse failure.
                logger.warning(
                    "notification_push_sender_crashed",
                    notification_id=str(notification.id),
                    transport=sender.transport,
                    exc_info=True,
                )
                retryable = True
                continue

            if outcome.outcome is PushOutcome.DELIVERED:
                delivered_any = True
            elif outcome.outcome is PushOutcome.DEVICE_GONE:
                logger.info(
                    "push_device_token_pruned",
                    user_id=str(notification.user_id),
                    platform=str(device.platform),
                    transport=sender.transport,
                    detail=outcome.detail,
                )
                await devices.delete_by_token(device.token)
            else:
                retryable = True
                logger.warning(
                    "notification_push_retry",
                    notification_id=str(notification.id),
                    transport=sender.transport,
                    detail=outcome.detail,
                )

        if retryable and not delivered_any:
            # Nothing got through and something might next time — leave it
            # for the next sweep, inside the stale window.
            continue

        # Either it reached a device, or every failure was terminal. Both
        # are decided; neither improves by trying again.
        notification.push_dispatched_at = now
        if delivered_any:
            pushed += 1

    if pushed:
        logger.info("notification_pushes_dispatched", count=pushed)
    return pushed


def _deep_link_data(notification: Notification) -> dict[str, str]:
    """The payload an app reads to open the right screen.

    Every value is stringified because FCM rejects a data payload
    containing anything else, and the notification's own ``payload`` is
    free-form JSON written by whatever rule created it — a workflow action
    can and does put numbers in there. The notification type and id ride
    along so a client can route without parsing the human-readable title.
    """
    data: dict[str, str] = {
        "notification_id": str(notification.id),
        "notification_type": notification.notification_type,
    }
    for key, value in (notification.payload or {}).items():
        if value is None:
            continue
        data[str(key)] = value if isinstance(value, str) else str(value)
    return data


async def _dispatch_pending_async() -> int:
    settings = get_settings()
    sender = build_push_sender(settings)
    if sender is None:
        # Push is not configured. Deliberately touches nothing — not even
        # to mark rows — so that supplying credentials later begins
        # delivering whatever is still current.
        return 0

    session_factory = _get_session_factory(settings)
    try:
        async with session_scope(session_factory) as session:
            return await dispatch_pending(session, settings, sender)
    finally:
        await sender.aclose()
        # See infrastructure/events/relay.py's identical fix: a pooled
        # asyncpg connection is bound to the event loop that opened it,
        # but this task's cached engine outlives any single
        # `asyncio.run()` loop.
        if _engine is not None:
            await _engine.dispose()


@celery_app.task(name="blinkengage.notifications.dispatch_pending_pushes")  # type: ignore[misc]
def dispatch_pending_pushes() -> int:
    return asyncio.run(_dispatch_pending_async())
