"""Builds an :class:`AutopilotService` inside a consumer process.

``AutopilotService`` deliberately takes a fully-wired
``ConversationService`` rather than building one, because sending a reply
needs MinIO, a channel-provider factory and a Redis realtime publisher —
infrastructure the application layer must not reach for itself. The API
gets those from FastAPI's dependency graph (``api/deps.py``); a consumer
process has no request scope, so it holds the same clients as
module-level singletons, created once and reused for the life of the
process. That pattern already existed inside ``ai_autopilot_consumer``;
it lives here now because the SLA-triggered consumer needs exactly the
same wiring, and one consumer importing another's private helpers would
be worse than a shared factory.
"""

from minio import Minio
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.application.services.autopilot_service import AutopilotService
from blinkengage.application.services.conversation_service import ConversationService
from blinkengage.application.services.ownership_service import OwnershipService
from blinkengage.core.config import Settings
from blinkengage.infrastructure.cache.redis import create_redis_client
from blinkengage.infrastructure.channels.factory import ChannelProviderFactory
from blinkengage.infrastructure.events.outbox_publisher import OutboxEventPublisher
from blinkengage.infrastructure.events.realtime_publisher import RealtimePublisher
from blinkengage.infrastructure.repositories.agent_repository import AgentRepository
from blinkengage.infrastructure.repositories.agent_skill_repository import AgentSkillRepository
from blinkengage.infrastructure.repositories.channel_config_repository import (
    ChannelConfigRepository,
)
from blinkengage.infrastructure.repositories.channel_connection_log_repository import (
    ChannelConnectionLogRepository,
)
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.conversation_repository import ConversationRepository
from blinkengage.infrastructure.repositories.conversation_transfer_repository import (
    ConversationTransferRepository,
)
from blinkengage.infrastructure.repositories.customer_repository import CustomerRepository
from blinkengage.infrastructure.repositories.department_repository import DepartmentRepository
from blinkengage.infrastructure.repositories.event_outbox_repository import EventOutboxRepository
from blinkengage.infrastructure.repositories.message_attachment_repository import (
    MessageAttachmentRepository,
)
from blinkengage.infrastructure.repositories.message_repository import MessageRepository
from blinkengage.infrastructure.repositories.ownership_repository import (
    OwnershipRepository,
)
from blinkengage.infrastructure.repositories.queue_repository import QueueRepository
from blinkengage.infrastructure.storage.attachment_store import AttachmentStore
from blinkengage.infrastructure.storage.s3_client import create_minio_client

_redis: Redis | None = None
_minio_client: Minio | None = None
_attachment_store: AttachmentStore | None = None


def get_attachment_store(settings: Settings) -> AttachmentStore:
    global _minio_client, _attachment_store
    if _minio_client is None:
        _minio_client = create_minio_client(settings)
    if _attachment_store is None:
        _attachment_store = AttachmentStore(_minio_client, bucket=settings.s3_bucket_attachments)
    return _attachment_store


def get_realtime_publisher(settings: Settings) -> RealtimePublisher:
    global _redis
    if _redis is None:
        _redis = create_redis_client(settings)
    return RealtimePublisher(_redis)


def get_provider_factory(settings: Settings) -> ChannelProviderFactory:
    return ChannelProviderFactory(
        realtime=get_realtime_publisher(settings), attachments=get_attachment_store(settings)
    )


def build_autopilot_service(*, session: AsyncSession, settings: Settings) -> AutopilotService:
    events = OutboxEventPublisher(EventOutboxRepository(session))
    conversations = ConversationRepository(session)
    messages = MessageRepository(session)
    conversation_service = ConversationService(
        conversations=conversations,
        messages=messages,
        attachments=MessageAttachmentRepository(session),
        channel_configs=ChannelConfigRepository(session),
        connection_logs=ChannelConnectionLogRepository(session),
        customers=CustomerRepository(session),
        attachment_store=get_attachment_store(settings),
        provider_factory=get_provider_factory(settings),
        events=events,
        settings=settings,
        transfers=ConversationTransferRepository(session),
        agents=AgentRepository(session),
        departments=DepartmentRepository(session),
        queues=QueueRepository(session),
        agent_skills=AgentSkillRepository(session),
        realtime=get_realtime_publisher(settings),
    )
    return AutopilotService(
        conversations=conversations,
        messages=messages,
        companies=CompanyRepository(session),
        events=events,
        conversation_service=conversation_service,
        # So a hand-off writes the ownership row that gives the conversation
        # back to its queue. Supplied here rather than defaulted inside the
        # service, because a service that built its own repository would be
        # reaching around the session this factory owns.
        ownership=OwnershipService(OwnershipRepository(session)),
    )
