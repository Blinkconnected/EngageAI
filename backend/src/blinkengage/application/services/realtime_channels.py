"""Redis pub/sub channel-naming conventions for the ephemeral realtime
tier (``infrastructure.events.realtime_publisher.RealtimePublisher``) —
kept in one place, not duplicated as ad hoc f-strings, since every
publisher and the one subscriber (``api/v1/endpoints/realtime.py``) must
agree on the exact same name.
"""

from uuid import UUID


def notification_channel_name(user_id: UUID) -> str:
    """A single user's personal channel — every open tab/device for that
    user subscribes to the same one. Carries bell-notification traffic
    (``NotificationService``) only."""
    return f"user:{user_id}:notifications"


def company_realtime_channel_name(company_id: UUID) -> str:
    """Every agent connected to this company's ``/ws/agent`` gateway
    subscribes to this same channel — a deliberately broad, company-wide
    broadcast (not a per-conversation channel) so no dynamic
    subscribe/unsubscribe protocol is needed over the WebSocket: a client
    just filters incoming frames by ``conversation_id`` itself. Carries
    ``message_received`` (see ``conversation_ingest_consumer.py`` and
    ``ConversationService.send_reply``) and ``customer_typing`` (see
    ``api/v1/endpoints/web_chat.py``) traffic — see
    ``docs/architecture/notifications.md``'s "Live conversation updates"
    section for why company-wide broadcast is the right tradeoff at this
    codebase's scale rather than a heavier per-conversation fan-out."""
    return f"company:{company_id}:realtime"
