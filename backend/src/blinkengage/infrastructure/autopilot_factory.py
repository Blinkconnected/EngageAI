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

from typing import Any

from minio import Minio
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.application.services.autopilot_service import AutopilotService
from blinkengage.application.services.conversation_service import ConversationService
from blinkengage.application.services.embedding_service import EmbeddingService
from blinkengage.application.services.faq_retrieval_service import FaqRetrievalService
from blinkengage.application.services.knowledge_retrieval_service import (
    KnowledgeRetrievalService,
)
from blinkengage.application.services.ownership_service import OwnershipService
from blinkengage.application.services.service_context_resolver import (
    ServiceContextResolver,
)
from blinkengage.application.services.sla_engine import SlaEngine
from blinkengage.core.config import Settings
from blinkengage.infrastructure.cache.redis import create_redis_client
from blinkengage.infrastructure.channels.factory import ChannelProviderFactory
from blinkengage.infrastructure.embeddings.factory import (
    build_embedding_provider_for_company,
)
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
from blinkengage.infrastructure.repositories.faq_repository import (
    FaqLexicalSearchRepository,
    FaqRepository,
)
from blinkengage.infrastructure.repositories.knowledge_index_repository import (
    EmbeddingRepository,
    KnowledgeChunkRepository,
)
from blinkengage.infrastructure.repositories.lexical_search_repository import (
    LexicalSearchRepository,
)
from blinkengage.infrastructure.repositories.message_attachment_repository import (
    MessageAttachmentRepository,
)
from blinkengage.infrastructure.repositories.message_repository import MessageRepository
from blinkengage.infrastructure.repositories.ownership_repository import (
    OwnershipRepository,
)
from blinkengage.infrastructure.repositories.queue_repository import QueueRepository
from blinkengage.infrastructure.repositories.routing_decision_repository import (
    RoutingDecisionRepository,
)
from blinkengage.infrastructure.repositories.service_directory_repository import (
    ContextBindingRepository,
    ServiceRepository,
)
from blinkengage.infrastructure.storage.attachment_store import AttachmentStore
from blinkengage.infrastructure.storage.s3_client import create_minio_client
from blinkengage.infrastructure.vector.factory import build_vector_index

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


def build_autopilot_service(
    *,
    session: AsyncSession,
    settings: Settings,
    company_ai_config: dict[str, Any] | None = None,
) -> AutopilotService:
    """``company_ai_config`` is the company's AI settings, used only to
    pick its embedding provider for retrieval — the same per-company
    override precedence ``api/deps.py`` applies. Passed in rather than
    re-read here because every caller has already loaded the company;
    omitting it falls back to the platform default provider, and a
    provider that resolves to ``None`` degrades retrieval to nothing
    rather than failing the run."""
    events = OutboxEventPublisher(EventOutboxRepository(session))
    conversations = ConversationRepository(session)
    messages = MessageRepository(session)
    embeddings = EmbeddingService(
        provider=build_embedding_provider_for_company(settings, company_ai_config),
        chunks=KnowledgeChunkRepository(session),
        embeddings=EmbeddingRepository(session),
        batch_size=settings.embedding_batch_size,
        max_attempts=settings.embedding_index_max_attempts,
    )
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
        ownership=OwnershipService(OwnershipRepository(session)),
        realtime=get_realtime_publisher(settings),
        # Without this, every reply AI sends settles no SLA clock: the
        # customer gets an answer in seconds and the first-response target
        # goes on running until it breaches. SlaLifecycle takes an optional
        # engine and quietly does nothing when it is absent, which is what
        # let this be missing without anything failing.
        sla=SlaEngine(session, RoutingDecisionRepository(session)),
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
        # So AI's hand-off says *why* on the conversation's own timeline.
        # ``RoutingDecisionKind.AI_RELEASED`` had Inspector wording and its
        # own rendering branch, and nothing that wrote it.
        decisions=RoutingDecisionRepository(session),
        # So the threshold on the Services screen is the one enforced.
        service_contexts=ServiceContextResolver(
            bindings=ContextBindingRepository(session),
            services=ServiceRepository(session),
        ),
        # So Autopilot answers from the company's own published material.
        # Built the same way `api/deps.py` builds them for
        # `/ai/knowledge-search`, against the same vector index — the
        # agent-facing endpoint and the unreviewed one must not ground on
        # different corpora.
        knowledge=KnowledgeRetrievalService(
            lexical=LexicalSearchRepository(session),
            chunks=KnowledgeChunkRepository(session),
            vector_index=build_vector_index(session),
            embeddings=embeddings,
            candidate_pool=settings.retrieval_candidate_pool,
        ),
        faqs=FaqRetrievalService(
            faqs=FaqRepository(session),
            lexical=FaqLexicalSearchRepository(session),
            vector_index=build_vector_index(session),
            embeddings=embeddings,
            candidate_pool=settings.retrieval_candidate_pool,
        ),
    )
