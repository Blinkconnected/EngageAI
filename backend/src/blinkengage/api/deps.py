"""FastAPI dependency providers.

These bridge the DI container to route handlers via ``Depends`` and are the
only place API code touches the container directly.
"""

from collections.abc import AsyncGenerator, Callable, Coroutine, Iterable
from datetime import timedelta
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Query, Request, WebSocket, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from minio import Minio
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.api.idempotency import IdempotencyGuard
from blinkengage.application.ai_tools import (
    DEFAULT_REGISTRY,
    ToolContext,
    ToolExecutor,
    ToolServices,
)
from blinkengage.application.services.agent_service import AgentService
from blinkengage.application.services.agent_skill_service import AgentSkillService
from blinkengage.application.services.ai_service import AiService
from blinkengage.application.services.audit_log_service import AuditLogService
from blinkengage.application.services.auth_service import AuthService
from blinkengage.application.services.autopilot_service import AutopilotService
from blinkengage.application.services.billable_event_service import BillableEventService
from blinkengage.application.services.billing_dashboard_service import (
    BillingDashboardService,
)
from blinkengage.application.services.billing_summary_service import BillingSummaryService
from blinkengage.application.services.channel_config_service import ChannelConfigService
from blinkengage.application.services.channel_connect_service import ChannelConnectService
from blinkengage.application.services.channel_diagnostics_service import (
    ChannelDiagnosticsService,
)
from blinkengage.application.services.collections_service import CollectionsService
from blinkengage.application.services.company_service import CompanyService
from blinkengage.application.services.connector_certification_service import (
    ConnectorCertificationService,
)
from blinkengage.application.services.conversation_deletion_service import (
    ConversationDeletionService,
)
from blinkengage.application.services.conversation_inspector import (
    ConversationInspectorService,
)
from blinkengage.application.services.conversation_memory_service import (
    ConversationMemoryErasureParticipant,
    ConversationMemoryService,
)
from blinkengage.application.services.conversation_service import ConversationService
from blinkengage.application.services.csat_service import CsatService
from blinkengage.application.services.customer_internal_rating_service import (
    CustomerInternalRatingService,
)
from blinkengage.application.services.customer_service import CustomerService
from blinkengage.application.services.department_service import DepartmentService
from blinkengage.application.services.device_token_service import DeviceTokenService
from blinkengage.application.services.embedding_service import EmbeddingService
from blinkengage.application.services.erp_config_service import ErpConfigService
from blinkengage.application.services.erp_sync_service import ErpSyncService
from blinkengage.application.services.faq_retrieval_service import FaqRetrievalService
from blinkengage.application.services.faq_service import FaqService
from blinkengage.application.services.feature_service import FeatureService
from blinkengage.application.services.financial_audit_service import FinancialAuditRecorder
from blinkengage.application.services.internal_note_service import InternalNoteService
from blinkengage.application.services.invoice_document_service import InvoiceDocumentService
from blinkengage.application.services.invoice_service import InvoiceService
from blinkengage.application.services.knowledge_record_service import (
    KnowledgeRecordService,
)
from blinkengage.application.services.knowledge_retrieval_service import (
    KnowledgeRetrievalService,
)
from blinkengage.application.services.knowledge_service import KnowledgeService
from blinkengage.application.services.learning_erasure_participant import (
    LearningErasureParticipant,
)
from blinkengage.application.services.learning_pattern_query_service import (
    LearningPatternQueryService,
)
from blinkengage.application.services.learning_query_service import LearningQueryService
from blinkengage.application.services.learning_settings_service import (
    LearningSettingsService,
)
from blinkengage.application.services.learning_shadow_service import LearningShadowService
from blinkengage.application.services.ledger_service import (
    LedgerReconciliation,
    LedgerService,
)
from blinkengage.application.services.memory_erasure_service import MemoryErasureService
from blinkengage.application.services.memory_manager import MemoryManager
from blinkengage.application.services.memory_query_service import MemoryQueryService
from blinkengage.application.services.message_redaction_service import MessageRedactionService
from blinkengage.application.services.notification_preference_service import (
    NotificationPreferenceService,
)
from blinkengage.application.services.notification_service import NotificationService
from blinkengage.application.services.ownership_service import OwnershipService
from blinkengage.application.services.payment_service import PaymentService
from blinkengage.application.services.platform_service import PlatformService
from blinkengage.application.services.platform_settings_service import (
    PlatformSettingsService,
)
from blinkengage.application.services.platform_user_service import PlatformUserService
from blinkengage.application.services.pricing_service import PricingService
from blinkengage.application.services.queue_service import QueueService
from blinkengage.application.services.quick_reply_service import QuickReplyService
from blinkengage.application.services.reporting_service import ReportingService
from blinkengage.application.services.revenue_service import RevenueService
from blinkengage.application.services.role_service import RoleService
from blinkengage.application.services.routing_rule_service import RoutingRuleService
from blinkengage.application.services.scheduler_health_service import SchedulerHealthService
from blinkengage.application.services.search_service import SearchService
from blinkengage.application.services.service_context_resolver import (
    ServiceContextResolver,
)
from blinkengage.application.services.service_directory_service import ServiceDirectoryService
from blinkengage.application.services.sla_engine import SlaEngine
from blinkengage.application.services.sla_policy_service import SlaPolicyService
from blinkengage.application.services.team_service import TeamService
from blinkengage.application.services.usage_service import UsageService
from blinkengage.application.services.verification_service import VerificationService
from blinkengage.application.services.web_chat_session_service import WebChatSessionService
from blinkengage.application.services.webhook_ingest_service import WebhookIngestService
from blinkengage.application.services.workflow_service import WorkflowService
from blinkengage.core.auth_context import AuthContext, PlatformContext
from blinkengage.core.config import Settings
from blinkengage.core.container import Container
from blinkengage.core.correlation import get_correlation_id
from blinkengage.core.rate_limit import FixedWindowRateLimiter, enforce_rate_limit
from blinkengage.core.security import InvalidTokenError, TokenType, decode_token
from blinkengage.domain.ai_provider import AiProvider
from blinkengage.domain.company_settings import is_ai_enabled
from blinkengage.domain.connector import DeploymentContext
from blinkengage.domain.exceptions import AiNotConfiguredError, EmailNotVerifiedError
from blinkengage.domain.features import FEATURES, is_known_feature
from blinkengage.domain.learning_cluster import (
    DEFAULT_JOIN_THRESHOLD,
    DEFAULT_MERGE_THRESHOLD,
)
from blinkengage.domain.rbac import is_known_permission
from blinkengage.domain.verification import is_blocked_before_verification
from blinkengage.infrastructure.ai.factory import build_ai_provider_for_company
from blinkengage.infrastructure.cache.chat_session_store import ChatSessionStore
from blinkengage.infrastructure.cache.idempotency import IdempotencyStore
from blinkengage.infrastructure.cache.presence import PresenceStore
from blinkengage.infrastructure.cache.redis import create_redis_client
from blinkengage.infrastructure.cache.refresh_tokens import RefreshTokenStore
from blinkengage.infrastructure.channels.factory import ChannelProviderFactory
from blinkengage.infrastructure.connectors.meta import META_APP
from blinkengage.infrastructure.database.models.company import Company, CompanyStatus
from blinkengage.infrastructure.database.models.user import User
from blinkengage.infrastructure.embeddings.factory import (
    build_embedding_provider_for_company,
)
from blinkengage.infrastructure.events.outbox_publisher import OutboxEventPublisher
from blinkengage.infrastructure.events.realtime_publisher import RealtimePublisher
from blinkengage.infrastructure.payments.registry import PaymentProviderRegistry
from blinkengage.infrastructure.repositories.agent_repository import AgentRepository
from blinkengage.infrastructure.repositories.agent_skill_repository import AgentSkillRepository
from blinkengage.infrastructure.repositories.audit_log_repository import (
    AuditLogRepository,
    LearningErasureCounter,
)
from blinkengage.infrastructure.repositories.billable_event_repository import (
    BillableEventRepository,
)
from blinkengage.infrastructure.repositories.billing_summary_repository import (
    BillingSummaryRepository,
)
from blinkengage.infrastructure.repositories.channel_config_repository import (
    ChannelConfigRepository,
)
from blinkengage.infrastructure.repositories.channel_connection_log_repository import (
    ChannelConnectionLogRepository,
)
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.conversation_deletion_repository import (
    ConversationDeletionRepository,
)
from blinkengage.infrastructure.repositories.conversation_repository import (
    ConversationRepository,
)
from blinkengage.infrastructure.repositories.conversation_transfer_repository import (
    ConversationTransferRepository,
)
from blinkengage.infrastructure.repositories.csat_repository import CsatResponseRepository
from blinkengage.infrastructure.repositories.customer_internal_rating_repository import (
    CustomerInternalRatingRepository,
)
from blinkengage.infrastructure.repositories.customer_repository import CustomerRepository
from blinkengage.infrastructure.repositories.department_repository import DepartmentRepository
from blinkengage.infrastructure.repositories.device_token_repository import (
    DeviceTokenRepository,
)
from blinkengage.infrastructure.repositories.erp_config_repository import ErpConfigRepository
from blinkengage.infrastructure.repositories.erp_customer_link_repository import (
    ErpCustomerLinkRepository,
)
from blinkengage.infrastructure.repositories.erp_synced_record_repository import (
    ErpSyncedRecordRepository,
)
from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
)
from blinkengage.infrastructure.repositories.faq_repository import (
    FaqLexicalSearchRepository,
    FaqRepository,
)
from blinkengage.infrastructure.repositories.financial_audit_repository import (
    FinancialAuditRepository,
)
from blinkengage.infrastructure.repositories.holiday_repository import HolidayRepository
from blinkengage.infrastructure.repositories.internal_note_repository import (
    InternalNoteRepository,
)
from blinkengage.infrastructure.repositories.invoicing_repository import (
    CreditNoteRepository,
    DocumentNumberRepository,
    InvoiceCompanyLookup,
    InvoiceLineRepository,
    InvoiceRepository,
    PaymentRepository,
)
from blinkengage.infrastructure.repositories.knowledge_index_repository import (
    EmbeddingRepository,
    KnowledgeChunkRepository,
    KnowledgeIndexStateRepository,
)
from blinkengage.infrastructure.repositories.knowledge_record_repository import (
    KnowledgeRecordRepository,
)
from blinkengage.infrastructure.repositories.knowledge_repository import (
    KnowledgeArticleRepository,
    KnowledgeCategoryRepository,
)
from blinkengage.infrastructure.repositories.learning_analysis_repository import (
    LearningAnomalyRepository,
    LearningClusterRepository,
    LearningTrendRepository,
)
from blinkengage.infrastructure.repositories.learning_repository import (
    LearningObservationRepository,
    LearningRunRepository,
)
from blinkengage.infrastructure.repositories.ledger_repository import LedgerRepository
from blinkengage.infrastructure.repositories.lexical_search_repository import (
    LexicalSearchRepository,
)
from blinkengage.infrastructure.repositories.memory_repository import (
    MemoryConfidenceSampleRepository,
    MemoryContradictionRepository,
    MemoryEvidenceRepository,
    MemoryFactRepository,
)
from blinkengage.infrastructure.repositories.message_attachment_repository import (
    MessageAttachmentRepository,
)
from blinkengage.infrastructure.repositories.message_repository import MessageRepository
from blinkengage.infrastructure.repositories.notification_preference_repository import (
    NotificationPreferenceRepository,
)
from blinkengage.infrastructure.repositories.notification_repository import (
    NotificationRepository,
)
from blinkengage.infrastructure.repositories.ownership_repository import OwnershipRepository
from blinkengage.infrastructure.repositories.payments_repository import (
    AllocationReversalRepository,
    PaymentIntentRepository,
    PaymentRefundRepository,
)
from blinkengage.infrastructure.repositories.platform_repository import PlatformRepository
from blinkengage.infrastructure.repositories.platform_settings_repository import (
    PlatformSettingsRepository,
)
from blinkengage.infrastructure.repositories.pricing_repository import (
    CompanyPricingAssignmentRepository,
    PricingAuditRepository,
    PricingCompanyLookup,
    PricingProfileRepository,
    PricingRateRepository,
)
from blinkengage.infrastructure.repositories.queue_repository import QueueRepository
from blinkengage.infrastructure.repositories.quick_reply_repository import QuickReplyRepository
from blinkengage.infrastructure.repositories.reporting_repository import ReportingRepository
from blinkengage.infrastructure.repositories.role_repository import RoleRepository
from blinkengage.infrastructure.repositories.routing_decision_repository import (
    RoutingDecisionRepository,
)
from blinkengage.infrastructure.repositories.routing_rule_repository import (
    RoutingRuleRepository,
)
from blinkengage.infrastructure.repositories.scheduler_run_repository import (
    SchedulerRunRepository,
)
from blinkengage.infrastructure.repositories.search_repository import SearchRepository
from blinkengage.infrastructure.repositories.service_directory_repository import (
    ContextBindingRepository,
    ServiceRepository,
)
from blinkengage.infrastructure.repositories.sla_policy_repository import SlaPolicyRepository
from blinkengage.infrastructure.repositories.tag_repository import TagRepository
from blinkengage.infrastructure.repositories.team_repository import TeamRepository
from blinkengage.infrastructure.repositories.usage_repository import (
    BillingPeriodRepository,
    UsagePeriodLineRepository,
    UsageRecordRepository,
)
from blinkengage.infrastructure.repositories.user_repository import UserRepository
from blinkengage.infrastructure.repositories.workflow_repository import (
    WorkflowDefinitionRepository,
)
from blinkengage.infrastructure.repositories.workflow_run_repository import (
    WorkflowRunRepository,
)
from blinkengage.infrastructure.storage.attachment_store import AttachmentStore
from blinkengage.infrastructure.storage.s3_client import create_minio_client
from blinkengage.infrastructure.vector.factory import build_vector_index

_bearer_scheme = HTTPBearer(auto_error=True)


def get_settings_dep(request: Request) -> Settings:
    container = cast(Container, request.app.state.container)
    return container.settings()


def get_settings_dep_ws(websocket: WebSocket) -> Settings:
    container = cast(Container, websocket.app.state.container)
    return container.settings()


async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession]:
    container = cast(Container, request.app.state.container)
    session_factory = container.session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_redis(request: Request) -> Redis:
    container = cast(Container, request.app.state.container)
    return container.redis()


async def get_db_session_ws(websocket: WebSocket) -> AsyncGenerator[AsyncSession]:
    """WebSocket-route counterpart to ``get_db_session`` — FastAPI
    dependencies for WebSocket routes must be typed with ``WebSocket``,
    not ``Request``, so this can't just reuse that function."""
    container = cast(Container, websocket.app.state.container)
    session_factory = container.session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_redis_ws(websocket: WebSocket) -> Redis:
    container = cast(Container, websocket.app.state.container)
    return container.redis()


def get_minio_client(request: Request) -> Minio:
    container = cast(Container, request.app.state.container)
    return container.minio_client()


def get_attachment_store(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    minio_client: Annotated[Minio, Depends(get_minio_client)],
) -> AttachmentStore:
    return AttachmentStore(minio_client, bucket=settings.s3_bucket_attachments)


def get_refresh_token_store(
    redis: Annotated[Redis, Depends(get_redis)],
) -> RefreshTokenStore:
    return RefreshTokenStore(redis)


def get_refresh_token_store_ws(
    redis: Annotated[Redis, Depends(get_redis_ws)],
) -> RefreshTokenStore:
    return RefreshTokenStore(redis)


def get_chat_session_store(redis: Annotated[Redis, Depends(get_redis)]) -> ChatSessionStore:
    return ChatSessionStore(redis)


def get_chat_session_store_ws(redis: Annotated[Redis, Depends(get_redis_ws)]) -> ChatSessionStore:
    return ChatSessionStore(redis)


def get_realtime_publisher_ws(
    redis: Annotated[Redis, Depends(get_redis_ws)],
) -> RealtimePublisher:
    return RealtimePublisher(redis)


def get_presence_store_ws(redis: Annotated[Redis, Depends(get_redis_ws)]) -> PresenceStore:
    return PresenceStore(redis)


def get_idempotency_guard(
    redis: Annotated[Redis, Depends(get_redis)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            max_length=255,
            description=(
                "Opt-in replay protection for a creating request. Present the same key "
                "to retry safely after a timeout; the original response is returned "
                "rather than the work being done twice."
            ),
        ),
    ] = None,
) -> IdempotencyGuard:
    return IdempotencyGuard(
        store=IdempotencyStore(redis),
        session=session,
        key=idempotency_key,
        reservation_ttl=timedelta(seconds=settings.idempotency_reservation_ttl_seconds),
        result_ttl=timedelta(hours=settings.idempotency_result_ttl_hours),
    )


def get_event_publisher(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OutboxEventPublisher:
    return OutboxEventPublisher(EventOutboxRepository(session))


def get_realtime_publisher(redis: Annotated[Redis, Depends(get_redis)]) -> RealtimePublisher:
    return RealtimePublisher(redis)


def get_channel_provider_factory(
    realtime: Annotated[RealtimePublisher, Depends(get_realtime_publisher)],
    attachments: Annotated[AttachmentStore, Depends(get_attachment_store)],
) -> ChannelProviderFactory:
    return ChannelProviderFactory(realtime=realtime, attachments=attachments)


def get_minio_client_ws(websocket: WebSocket) -> Minio:
    container = cast(Container, websocket.app.state.container)
    return container.minio_client()


def get_attachment_store_ws(
    settings: Annotated[Settings, Depends(get_settings_dep_ws)],
    minio_client: Annotated[Minio, Depends(get_minio_client_ws)],
) -> AttachmentStore:
    return AttachmentStore(minio_client, bucket=settings.s3_bucket_attachments)


def get_channel_provider_factory_ws(
    realtime: Annotated[RealtimePublisher, Depends(get_realtime_publisher_ws)],
    attachments: Annotated[AttachmentStore, Depends(get_attachment_store_ws)],
) -> ChannelProviderFactory:
    return ChannelProviderFactory(realtime=realtime, attachments=attachments)


def get_event_publisher_ws(
    session: Annotated[AsyncSession, Depends(get_db_session_ws)],
) -> OutboxEventPublisher:
    return OutboxEventPublisher(EventOutboxRepository(session))


def get_auth_service(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    refresh_tokens: Annotated[RefreshTokenStore, Depends(get_refresh_token_store)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
) -> AuthService:
    return AuthService(
        settings=settings,
        session=session,
        companies=CompanyRepository(session),
        users=UserRepository(session),
        roles=RoleRepository(session),
        refresh_tokens=refresh_tokens,
        events=events,
    )


def get_current_auth(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> AuthContext:
    try:
        payload = decode_token(
            credentials.credentials, settings=settings, expected_type=TokenType.ACCESS
        )
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    company_id_claim = payload.get("company_id")
    if company_id_claim is None:
        # A platform-administrator token. It carries no company, so it
        # must never reach a tenant endpoint: every one of those reads
        # `auth.company_id` straight into a repository filter, and there
        # is no sane tenant to substitute. Rejected here, once, rather
        # than relying on ~100 endpoints to notice.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "This is a platform administrator account, which has no company context. "
                "Use the platform endpoints under /platform."
            ),
        )

    return AuthContext(
        user_id=UUID(payload["sub"]),
        company_id=UUID(company_id_claim),
        permissions=frozenset(payload.get("permissions", [])),
    )


async def get_platform_auth(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PlatformContext:
    """Authenticates a platform (super) administrator for `/platform/*`.

    Unlike `get_current_auth`, the flag is re-read from the database on
    every request rather than trusted from the token. Platform authority
    is the most privileged thing in the system, so revoking it must take
    effect immediately — not after the access token's 15-minute window
    (the tradeoff `auth_context.py` documents and accepts for ordinary
    tenant permissions).
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(
            credentials.credentials, settings=settings, expected_type=TokenType.ACCESS
        )
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = await UserRepository(session).get_by_id(UUID(payload["sub"]))
    if user is None or not user.is_active or not user.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform administrator access is required.",
        )
    return PlatformContext(user_id=user.id, read_only=user.platform_read_only)


async def _assert_company_active(session: AsyncSession, company_id: UUID) -> None:
    """Refuses a request whose company is suspended or gone.

    Checked per request rather than only at sign-in: an access token
    minted before a suspension stays cryptographically valid for its full
    15-minute life, so a token-only check would let a just-suspended
    company keep working. Suspension is an account-state decision a
    platform operator expects to take effect immediately, unlike an
    ordinary permission change (see `auth_context.py` on that tradeoff),
    which is why this one accepts a per-request lookup — an indexed
    primary-key read.
    """
    company = await CompanyRepository(session).get_by_id(company_id)
    if company is None or company.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="This workspace is no longer active."
        )
    if company.status is CompanyStatus.SUSPENDED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This workspace has been suspended. Please contact your administrator.",
        )


async def get_active_auth(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuthContext:
    """`get_current_auth` plus a company-state check. This is what
    `require_permission` depends on, so every permission-gated route —
    i.e. effectively the whole tenant API — enforces suspension."""
    await _assert_company_active(session, auth.company_id)
    return auth


async def get_current_user(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> User:
    user = await UserRepository(session).get_by_id(auth.user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Account is no longer active"
        )
    await _assert_company_active(session, auth.company_id)
    return user


def get_department_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
) -> DepartmentService:
    return DepartmentService(
        departments=DepartmentRepository(session),
        agents=AgentRepository(session),
        events=events,
    )


def get_team_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
) -> TeamService:
    return TeamService(
        teams=TeamRepository(session), agents=AgentRepository(session), events=events
    )


def get_agent_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
    refresh_tokens: Annotated[RefreshTokenStore, Depends(get_refresh_token_store)],
) -> AgentService:
    return AgentService(
        session=session,
        settings=settings,
        agents=AgentRepository(session),
        users=UserRepository(session),
        roles=RoleRepository(session),
        companies=CompanyRepository(session),
        events=events,
        refresh_tokens=refresh_tokens,
    )


def get_agent_service_ws(
    session: Annotated[AsyncSession, Depends(get_db_session_ws)],
    settings: Annotated[Settings, Depends(get_settings_dep_ws)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher_ws)],
    refresh_tokens: Annotated[RefreshTokenStore, Depends(get_refresh_token_store_ws)],
) -> AgentService:
    return AgentService(
        session=session,
        settings=settings,
        agents=AgentRepository(session),
        users=UserRepository(session),
        roles=RoleRepository(session),
        companies=CompanyRepository(session),
        events=events,
        refresh_tokens=refresh_tokens,
    )


def get_customer_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
) -> CustomerService:
    return CustomerService(
        customers=CustomerRepository(session), tags=TagRepository(session), events=events
    )


def get_customer_internal_rating_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
) -> CustomerInternalRatingService:
    return CustomerInternalRatingService(
        ratings=CustomerInternalRatingRepository(session),
        customers=CustomerRepository(session),
        events=events,
    )


def get_audit_log_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuditLogService:
    return AuditLogService(audit_logs=AuditLogRepository(session))


def get_channel_connect_service(
    redis: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> ChannelConnectService:
    """The connection wizard.

    ``configured_apps`` is where the three deployment modes come from: a
    Meta app id and secret present — from the environment or, overriding it,
    the encrypted platform settings — means consent is on offer; absent means
    the guided manual path. One resolver, so no screen has to ask why.
    """
    return ChannelConnectService(redis=redis, context=_deployment_context(settings))


def _deployment_context(settings: Settings) -> DeploymentContext:
    """What this installation happens to hold.

    One resolver, because two would drift: the wizard and the diagnostics
    panel must agree about whether OAuth is on offer, and a connector
    resolving differently in the two would be a channel that connects one way
    and reports another.
    """
    apps: set[str] = set()
    if settings.meta_app_id and settings.meta_app_secret:
        apps.add(META_APP)
    return DeploymentContext(
        public_base_url=settings.public_base_url.rstrip("/"),
        configured_apps=frozenset(apps),
        platform_version=settings.platform_version,
    )


def get_connector_certification_service(
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> ConnectorCertificationService:
    """The certification runner. Needs no repository — it exercises a
    connector against a provider and scores what came back."""
    return ConnectorCertificationService(context=_deployment_context(settings))


def get_channel_diagnostics_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> ChannelDiagnosticsService:
    """Channel diagnostics, for support."""
    return ChannelDiagnosticsService(
        logs=ChannelConnectionLogRepository(session),
        context=_deployment_context(settings),
    )


def get_channel_config_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    provider_factory: Annotated[ChannelProviderFactory, Depends(get_channel_provider_factory)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
) -> ChannelConfigService:
    return ChannelConfigService(
        channel_configs=ChannelConfigRepository(session),
        connection_logs=ChannelConnectionLogRepository(session),
        provider_factory=provider_factory,
        events=events,
        settings=settings,
    )


def get_web_chat_session_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    sessions: Annotated[ChatSessionStore, Depends(get_chat_session_store)],
) -> WebChatSessionService:
    return WebChatSessionService(
        channel_configs=ChannelConfigRepository(session),
        customers=CustomerRepository(session),
        sessions=sessions,
        session_ttl=timedelta(hours=settings.webchat_session_ttl_hours),
    )


def _realtime_from(settings: Settings) -> RealtimePublisher:
    """A publisher built from settings rather than from a request.

    The FastAPI dependencies above resolve these through the container; the
    start-up guard has no request to resolve against and must not therefore
    build a lesser service. Kept private so request handlers keep using the
    container and only the guard reaches for this.
    """
    return RealtimePublisher(create_redis_client(settings))


def _attachment_store_from(settings: Settings) -> AttachmentStore:
    return AttachmentStore(create_minio_client(settings), bucket=settings.s3_bucket_attachments)


def build_conversation_service(
    *,
    session: AsyncSession,
    settings: Settings,
    attachment_store: AttachmentStore | None = None,
    provider_factory: ChannelProviderFactory | None = None,
    events: OutboxEventPublisher | None = None,
    realtime: RealtimePublisher | None = None,
) -> ConversationService:
    """The one place a production ConversationService is assembled.

    Extracted from the FastAPI dependencies below so the HTTP path, the
    WebSocket path and the start-up wiring guard all build the *same* object.
    A guard that constructed its own copy would pass while the real one stayed
    half-wired, which is precisely the failure it exists to catch.

    The four transport-shaped collaborators may be omitted, and are then
    built from settings rather than passed as ``None``. That is what makes the
    start-up guard meaningful: it assembles the *same* object a request does,
    so a collaborator missing in production is missing in the guard too.
    Passing ``None`` through would have given the guard a different, weaker
    service than the one serving traffic — the exact blind spot it exists to
    close. All four are lazy: creating a client opens no connection.
    """
    realtime = realtime or _realtime_from(settings)
    attachment_store = attachment_store or _attachment_store_from(settings)
    provider_factory = provider_factory or ChannelProviderFactory(
        realtime=realtime, attachments=attachment_store
    )
    events = events or OutboxEventPublisher(EventOutboxRepository(session))
    return ConversationService(
        # Wired here rather than made required constructor arguments: the
        # ~25 tests that build this service directly keep working, and
        # production gets the clocks and the ownership timeline. The
        # start-up guard (``core/wiring.py``) is what makes "production
        # gets them" a fact rather than an intention.
        sla=SlaEngine(session, RoutingDecisionRepository(session)),
        ownership=OwnershipService(OwnershipRepository(session)),
        conversations=ConversationRepository(session),
        messages=MessageRepository(session),
        attachments=MessageAttachmentRepository(session),
        channel_configs=ChannelConfigRepository(session),
        connection_logs=ChannelConnectionLogRepository(session),
        customers=CustomerRepository(session),
        attachment_store=attachment_store,
        provider_factory=provider_factory,
        events=events,
        settings=settings,
        transfers=ConversationTransferRepository(session),
        agents=AgentRepository(session),
        departments=DepartmentRepository(session),
        queues=QueueRepository(session),
        agent_skills=AgentSkillRepository(session),
        realtime=realtime,
    )


def get_conversation_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    attachment_store: Annotated[AttachmentStore, Depends(get_attachment_store)],
    provider_factory: Annotated[ChannelProviderFactory, Depends(get_channel_provider_factory)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
    realtime: Annotated[RealtimePublisher, Depends(get_realtime_publisher)],
) -> ConversationService:
    return build_conversation_service(
        session=session,
        settings=settings,
        attachment_store=attachment_store,
        provider_factory=provider_factory,
        events=events,
        realtime=realtime,
    )


def get_conversation_service_ws(
    session: Annotated[AsyncSession, Depends(get_db_session_ws)],
    settings: Annotated[Settings, Depends(get_settings_dep_ws)],
    attachment_store: Annotated[AttachmentStore, Depends(get_attachment_store_ws)],
    provider_factory: Annotated[ChannelProviderFactory, Depends(get_channel_provider_factory_ws)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher_ws)],
    realtime: Annotated[RealtimePublisher, Depends(get_realtime_publisher_ws)],
) -> ConversationService:
    return build_conversation_service(
        session=session,
        settings=settings,
        attachment_store=attachment_store,
        provider_factory=provider_factory,
        events=events,
        realtime=realtime,
    )


def get_user_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> UserRepository:
    return UserRepository(session)


def get_message_redaction_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    attachment_store: Annotated[AttachmentStore, Depends(get_attachment_store)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
) -> MessageRedactionService:
    return MessageRedactionService(
        session=session, attachment_store=attachment_store, events=events
    )


def get_conversation_inspector(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ConversationInspectorService:
    """The Black Box assembler. Reads only — it writes nothing anywhere."""
    return ConversationInspectorService(
        session=session,
        ownership=OwnershipService(OwnershipRepository(session)),
        sla=SlaEngine(session, RoutingDecisionRepository(session)),
        decisions=RoutingDecisionRepository(session),
        services=ServiceContextResolver(
            bindings=ContextBindingRepository(session),
            services=ServiceRepository(session),
        ),
    )


def get_sla_engine(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SlaEngine:
    return SlaEngine(session, RoutingDecisionRepository(session))


def get_routing_decision_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RoutingDecisionRepository:
    return RoutingDecisionRepository(session)


def get_ownership_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OwnershipService:
    return OwnershipService(OwnershipRepository(session))


def get_scheduler_health_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SchedulerHealthService:
    return SchedulerHealthService(SchedulerRunRepository(session))


def get_service_directory_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ServiceDirectoryService:
    return ServiceDirectoryService(
        services=ServiceRepository(session), queues=QueueRepository(session)
    )


def get_queue_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
) -> QueueService:
    return QueueService(
        queues=QueueRepository(session),
        agent_skills=AgentSkillRepository(session),
        sla_policies=SlaPolicyRepository(session),
        services=ServiceRepository(session),
        events=events,
    )


def get_search_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SearchService:
    return SearchService(search=SearchRepository(session))


def get_agent_skill_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AgentSkillService:
    return AgentSkillService(
        agents=AgentRepository(session), agent_skills=AgentSkillRepository(session)
    )


def get_routing_rule_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
) -> RoutingRuleService:
    return RoutingRuleService(routing_rules=RoutingRuleRepository(session), events=events)


def get_role_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
) -> RoleService:
    return RoleService(roles=RoleRepository(session), events=events)


def get_sla_policy_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
) -> SlaPolicyService:
    return SlaPolicyService(
        policies=SlaPolicyRepository(session),
        holidays=HolidayRepository(session),
        companies=CompanyRepository(session),
        events=events,
    )


def get_workflow_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
) -> WorkflowService:
    return WorkflowService(
        workflows=WorkflowDefinitionRepository(session),
        runs=WorkflowRunRepository(session),
        events=events,
    )


def get_notification_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    realtime: Annotated[RealtimePublisher, Depends(get_realtime_publisher)],
) -> NotificationService:
    return NotificationService(
        notifications=NotificationRepository(session),
        companies=CompanyRepository(session),
        realtime=realtime,
    )


def get_notification_service_ws(
    session: Annotated[AsyncSession, Depends(get_db_session_ws)],
    realtime: Annotated[RealtimePublisher, Depends(get_realtime_publisher_ws)],
) -> NotificationService:
    return NotificationService(
        notifications=NotificationRepository(session),
        companies=CompanyRepository(session),
        realtime=realtime,
    )


def get_conversation_deletion_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    conversations: Annotated[ConversationService, Depends(get_conversation_service)],
    notifications: Annotated[NotificationService, Depends(get_notification_service)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
) -> ConversationDeletionService:
    """Composed from the conversation service rather than the repository:
    approving a request performs the same deletion — same soft delete,
    same ``conversation.deleted`` event — that a direct delete does, so
    the two paths cannot drift apart."""
    return ConversationDeletionService(
        requests=ConversationDeletionRepository(session),
        conversations=conversations,
        customers=CustomerRepository(session),
        roles=RoleRepository(session),
        notifications=notifications,
        events=events,
    )


def get_notification_preference_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> NotificationPreferenceService:
    return NotificationPreferenceService(preferences=NotificationPreferenceRepository(session))


def get_device_token_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DeviceTokenService:
    return DeviceTokenService(devices=DeviceTokenRepository(session))


async def get_ai_provider(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AiProvider | None:
    """Prefers the calling company's own provider override
    (``Company.ai_config``) over the platform-level default — see
    ``build_ai_provider_for_company``."""
    company = await CompanyRepository(session).get_by_id(auth.company_id)
    company_ai_config = company.ai_config if company else None
    return build_ai_provider_for_company(settings, company_ai_config)


def get_ai_service(
    provider: Annotated[AiProvider | None, Depends(get_ai_provider)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
) -> AiService:
    return AiService(provider=provider, events=events)


def get_autopilot_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
    conversation_service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> AutopilotService:
    return AutopilotService(
        conversations=ConversationRepository(session),
        messages=MessageRepository(session),
        companies=CompanyRepository(session),
        events=events,
        conversation_service=conversation_service,
    )


#: Feature keys to their human names, so a 402 names the capability
#: rather than repeating a slug at somebody who never chose it.
_FEATURE_NAMES: dict[str, str] = {feature.key: feature.name for feature in FEATURES}


def get_feature_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
) -> FeatureService:
    return FeatureService(companies=CompanyRepository(session), events=events)


def require_feature(
    key: str,
) -> Callable[[AuthContext, FeatureService], Coroutine[Any, Any, AuthContext]]:
    """Dependency factory: ``Depends(require_feature("ai"))``.

    Distinct from ``require_permission`` and stacked *with* it, never
    instead of it. They answer different questions: a permission asks
    "may this user do it?", a feature asks "has this company bought it?"
    — and the honest answer to a caller who has the permission but not
    the entitlement is 402 Payment Required, not 403 Forbidden. Telling
    an administrator they lack permission for something their own role
    grants would send them to edit roles that were never the problem.

    Fails fast at import time on an unknown key, like
    ``require_permission``.
    """
    if not is_known_feature(key):
        raise ValueError(f"Unknown feature key: {key!r}")

    async def _check(
        auth: Annotated[AuthContext, Depends(get_active_auth)],
        features: Annotated[FeatureService, Depends(get_feature_service)],
    ) -> AuthContext:
        enabled = await features.enabled_features(auth.company_id)
        if not enabled.get(key, True):
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=(
                    f"{_FEATURE_NAMES.get(key, key)} is not enabled for this workspace. "
                    "Contact your provider to enable it."
                ),
            )
        return auth

    return _check


async def require_export_feature(
    auth: Annotated[AuthContext, Depends(get_active_auth)],
    features: Annotated[FeatureService, Depends(get_feature_service)],
    export: Annotated[str | None, Query()] = None,
) -> None:
    """Gates report *downloads* without gating reports themselves.

    Applied to the whole reports router, but only bites when an `export`
    query parameter is actually present — a plan that excludes exports
    still gets to see its dashboards on screen, which is the difference
    between a tiered product and a broken one.
    """
    if export is None:
        return
    enabled = await features.enabled_features(auth.company_id)
    if not enabled.get("reports_export", True):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                f"{_FEATURE_NAMES['reports_export']} is not enabled for this workspace. "
                "Contact your provider to enable it."
            ),
        )


def get_pricing_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
) -> PricingService:
    return PricingService(
        rates=PricingRateRepository(session),
        assignments=CompanyPricingAssignmentRepository(session),
        profiles=PricingProfileRepository(session),
        audit=PricingAuditRepository(session),
        companies=PricingCompanyLookup(session),
        users=UserRepository(session),
        events=events,
    )


def get_usage_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
    pricing: Annotated[PricingService, Depends(get_pricing_service)],
) -> UsageService:
    return UsageService(
        periods=BillingPeriodRepository(session),
        records=UsageRecordRepository(session),
        lines=UsagePeriodLineRepository(session),
        pricing=pricing,
        events=events,
    )


def get_financial_audit_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> FinancialAuditRepository:
    return FinancialAuditRepository(session)


def get_invoice_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
) -> InvoiceService:
    return InvoiceService(
        invoices=InvoiceRepository(session),
        lines=InvoiceLineRepository(session),
        credit_notes=CreditNoteRepository(session),
        payments=PaymentRepository(session),
        numbers=DocumentNumberRepository(session),
        periods=BillingPeriodRepository(session),
        period_lines=UsagePeriodLineRepository(session),
        companies=InvoiceCompanyLookup(session),
        events=events,
        audit=FinancialAuditRecorder(FinancialAuditRepository(session)),
        ledger=build_ledger_service(session),
    )


def build_ledger_service(session: AsyncSession) -> LedgerService:
    """The ledger, on the caller's session.

    Deliberately the *same* session as the operation being recorded: an
    entry written on another connection can disagree with the thing it
    records, and a ledger that disagrees is worse than none.
    """
    return LedgerService(
        entries=LedgerRepository(session), numbers=DocumentNumberRepository(session)
    )


def get_ledger_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> LedgerService:
    return build_ledger_service(session)


def get_ledger_reconciliation(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> LedgerReconciliation:
    return LedgerReconciliation(session=session, ledger=build_ledger_service(session))


def get_payment_providers(
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> PaymentProviderRegistry:
    """Built per request from settings rather than cached at import.

    The adapters are cheap (an httpx client per call, an in-memory
    token) and building them here means a credential change takes effect
    on redeploy without a stale registry surviving in module state.
    """
    return PaymentProviderRegistry.from_settings(settings)


def get_payment_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    invoice_service: Annotated[InvoiceService, Depends(get_invoice_service)],
    providers: Annotated[PaymentProviderRegistry, Depends(get_payment_providers)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> PaymentService:
    return PaymentService(
        intents=PaymentIntentRepository(session),
        refunds=PaymentRefundRepository(session),
        reversals=AllocationReversalRepository(session),
        payments=PaymentRepository(session),
        invoices=InvoiceRepository(session),
        invoice_service=invoice_service,
        providers=providers,
        audit=FinancialAuditRecorder(FinancialAuditRepository(session)),
        ledger=build_ledger_service(session),
        settings=settings,
    )


def get_billing_summary_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    pricing: Annotated[PricingService, Depends(get_pricing_service)],
) -> BillingSummaryService:
    return BillingSummaryService(
        summaries=BillingSummaryRepository(session),
        periods=BillingPeriodRepository(session),
        records=UsageRecordRepository(session),
        pricing=pricing,
        session=session,
    )


def get_billing_dashboard_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    summary_service: Annotated[BillingSummaryService, Depends(get_billing_summary_service)],
    invoice_service: Annotated[InvoiceService, Depends(get_invoice_service)],
    usage_service: Annotated[UsageService, Depends(get_usage_service)],
    pricing: Annotated[PricingService, Depends(get_pricing_service)],
    providers: Annotated[PaymentProviderRegistry, Depends(get_payment_providers)],
) -> BillingDashboardService:
    """The tenant's billing dashboard.

    Takes the payment provider registry so the payment methods it offers are
    the ones this deployment has actually configured — a dashboard with a
    hardcoded list eventually shows a button that cannot work.
    """
    return BillingDashboardService(
        billable=BillableEventService(events=BillableEventRepository(session), usage=usage_service),
        summaries=BillingSummaryRepository(session),
        summary_service=summary_service,
        periods=BillingPeriodRepository(session),
        companies=CompanyRepository(session),
        invoices=invoice_service,
        ledger=build_ledger_service(session),
        pricing=pricing,
        providers=providers,
    )


def get_collections_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    invoice_service: Annotated[InvoiceService, Depends(get_invoice_service)],
    notifications: Annotated[NotificationService, Depends(get_notification_service)],
) -> CollectionsService:
    return CollectionsService(
        session=session,
        invoice_service=invoice_service,
        notifications=notifications,
        audit=FinancialAuditRecorder(FinancialAuditRepository(session)),
    )


def get_revenue_service(
    ledger: Annotated[LedgerService, Depends(get_ledger_service)],
    collections: Annotated[CollectionsService, Depends(get_collections_service)],
) -> RevenueService:
    return RevenueService(ledger=ledger, collections=collections)


def get_platform_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
) -> PlatformService:
    return PlatformService(
        companies=CompanyRepository(session),
        platform=PlatformRepository(session),
        events=events,
    )


def get_tag_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TagRepository:
    return TagRepository(session)


def get_knowledge_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
) -> KnowledgeService:
    return KnowledgeService(
        categories=KnowledgeCategoryRepository(session),
        articles=KnowledgeArticleRepository(session),
        events=events,
    )


def get_knowledge_record_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
) -> KnowledgeRecordService:
    return KnowledgeRecordService(
        records=KnowledgeRecordRepository(session),
        events=events,
    )


def get_learning_query_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> LearningQueryService:
    """Reading Learning. Phase 1 exposes no writer at all — observations
    are assembled by consumers, never by a request."""
    return LearningQueryService(
        observations=LearningObservationRepository(session),
        runs=LearningRunRepository(session),
        companies=CompanyRepository(session),
        erasures=LearningErasureCounter(session),
    )


def get_learning_pattern_query_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> LearningPatternQueryService:
    """Reading what phase 2 discovered. No writer is exposed: clusters,
    trends and anomalies are produced by sweeps, never by a request."""
    return LearningPatternQueryService(
        clusters=LearningClusterRepository(session),
        trends=LearningTrendRepository(session),
        anomalies=LearningAnomalyRepository(session),
        observations=LearningObservationRepository(session),
        runs=LearningRunRepository(session),
    )


def get_learning_shadow_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> LearningShadowService:
    """Shadow validation. Read-only by construction: it holds repositories
    and calls none of their write methods."""
    return LearningShadowService(
        clusters=LearningClusterRepository(session),
        trends=LearningTrendRepository(session),
        anomalies=LearningAnomalyRepository(session),
        observations=LearningObservationRepository(session),
        runs=LearningRunRepository(session),
    )


def get_learning_settings_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
) -> LearningSettingsService:
    """Threshold changes. The one writer on the intelligence surface, and
    the reason it publishes: a change reshapes every cluster the platform
    will produce, so it belongs on the audit trail rather than only in a
    settings blob."""
    return LearningSettingsService(
        companies=CompanyRepository(session),
        clusters=LearningClusterRepository(session),
        events=events,
        # The platform floor a company's override resolves against. Taken
        # from the domain constants, which is where the measured values
        # live — an environment-level override for these is a reasonable
        # next step and is not needed for a company to set its own.
        platform_defaults={
            "cluster_join_threshold": DEFAULT_JOIN_THRESHOLD,
            "cluster_merge_threshold": DEFAULT_MERGE_THRESHOLD,
        },
    )


def get_memory_manager(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
) -> MemoryManager:
    """The **only** writer of memory.

    Every route that changes a fact takes this; none takes a memory
    repository. That is what makes "one door" a property of the wiring
    rather than a rule people are asked to remember — and an AST guard
    fails the build if any module outside the Manager calls a memory
    write method.
    """
    return MemoryManager(
        facts=MemoryFactRepository(session),
        evidence=MemoryEvidenceRepository(session),
        samples=MemoryConfidenceSampleRepository(session),
        contradictions=MemoryContradictionRepository(session),
        events=events,
    )


def get_memory_query_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> MemoryQueryService:
    """Reading memory. Deliberately has no write method to reach for."""
    return MemoryQueryService(
        facts=MemoryFactRepository(session),
        evidence=MemoryEvidenceRepository(session),
        companies=CompanyRepository(session),
        recompute_interval_seconds=settings.memory_recompute_interval_seconds,
    )


def get_conversation_memory_service(
    redis: Annotated[Redis, Depends(get_redis)],
) -> ConversationMemoryService:
    return ConversationMemoryService(redis)


def get_memory_erasure_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
    manager: Annotated[MemoryManager, Depends(get_memory_manager)],
    working_memory: Annotated[ConversationMemoryService, Depends(get_conversation_memory_service)],
) -> MemoryErasureService:
    """Erasure, which must complete — see the service's own docstring for
    why it is separate from the Manager."""
    return MemoryErasureService(
        facts=MemoryFactRepository(session),
        evidence=MemoryEvidenceRepository(session),
        embeddings=EmbeddingRepository(session),
        events=events,
        recompute=manager,
        # Every context holding data about the subject registers here.
        # Working memory is keyed by conversation, so erasing a *customer*
        # needs their conversations resolved first — which is the
        # Conversation context's lookup, not Memory's, and is why this is
        # a participant rather than a branch inside the erasure service.
        participants=(
            ConversationMemoryErasureParticipant(
                memory=working_memory, conversations=ConversationRepository(session)
            ),
            # Learning holds observations keyed to the customer. Without
            # this the erasure report would assert complete deletion while
            # four tables still held the subject — B5 from the freeze
            # review, and the reason participation is a registration
            # rather than a branch inside the erasure service.
            LearningErasureParticipant(observations=LearningObservationRepository(session)),
        ),
    )


async def get_embedding_service(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> EmbeddingService:
    """Prefers the calling company's own embedding override, falling back
    to the platform default — the same precedence ``get_ai_provider`` uses,
    resolved separately because the two providers are chosen separately."""
    company = await CompanyRepository(session).get_by_id(auth.company_id)
    company_ai_config = company.ai_config if company else None
    return EmbeddingService(
        provider=build_embedding_provider_for_company(settings, company_ai_config),
        chunks=KnowledgeChunkRepository(session),
        embeddings=EmbeddingRepository(session),
        index_state=KnowledgeIndexStateRepository(session),
        batch_size=settings.embedding_batch_size,
        max_attempts=settings.embedding_index_max_attempts,
    )


async def get_knowledge_retrieval_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    embeddings: Annotated[EmbeddingService, Depends(get_embedding_service)],
) -> KnowledgeRetrievalService:
    return KnowledgeRetrievalService(
        lexical=LexicalSearchRepository(session),
        chunks=KnowledgeChunkRepository(session),
        # Chosen by the session's dialect, not by configuration — which
        # index can run is a fact about the database, not a preference.
        vector_index=build_vector_index(session),
        embeddings=embeddings,
        candidate_pool=settings.retrieval_candidate_pool,
    )


def get_faq_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
) -> FaqService:
    return FaqService(faqs=FaqRepository(session), events=events)


async def get_faq_retrieval_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    embeddings: Annotated[EmbeddingService, Depends(get_embedding_service)],
) -> FaqRetrievalService:
    return FaqRetrievalService(
        faqs=FaqRepository(session),
        lexical=FaqLexicalSearchRepository(session),
        # Same index, same session-dialect choice as article retrieval —
        # FAQ vectors live in the same table under a different owner type.
        vector_index=build_vector_index(session),
        embeddings=embeddings,
        candidate_pool=settings.retrieval_candidate_pool,
    )


def get_quick_reply_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
) -> QuickReplyService:
    return QuickReplyService(quick_replies=QuickReplyRepository(session), events=events)


def get_internal_note_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
) -> InternalNoteService:
    return InternalNoteService(
        notes=InternalNoteRepository(session),
        conversations=ConversationRepository(session),
        events=events,
    )


def get_webhook_ingest_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    factory: Annotated[ChannelProviderFactory, Depends(get_channel_provider_factory)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
) -> WebhookIngestService:
    return WebhookIngestService(
        channel_configs=ChannelConfigRepository(session), factory=factory, events=events
    )


def get_invoice_document_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> InvoiceDocumentService:
    return InvoiceDocumentService(session, issuer_name=settings.app_name)


def get_company_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
    logos: Annotated[AttachmentStore, Depends(get_attachment_store)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> CompanyService:
    return CompanyService(
        companies=CompanyRepository(session), events=events, logos=logos, settings=settings
    )


def get_erp_config_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
) -> ErpConfigService:
    return ErpConfigService(
        erp_configs=ErpConfigRepository(session),
        companies=CompanyRepository(session),
        events=events,
    )


def get_erp_sync_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
) -> ErpSyncService:
    return ErpSyncService(
        erp_configs=ErpConfigRepository(session),
        customer_links=ErpCustomerLinkRepository(session),
        synced_records=ErpSyncedRecordRepository(session),
        customers=CustomerRepository(session),
        companies=CompanyRepository(session),
        events=events,
    )


def get_reporting_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ReportingService:
    return ReportingService(reporting=ReportingRepository(session), agents=AgentRepository(session))


def get_csat_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
) -> CsatService:
    return CsatService(
        conversations=ConversationRepository(session),
        responses=CsatResponseRepository(session),
        customers=CustomerRepository(session),
        events=events,
        settings=settings,
    )


def require_permission(
    code: str,
) -> Callable[..., Coroutine[Any, Any, AuthContext]]:
    """Dependency factory: ``Depends(require_permission("customers.manage"))``.

    Fails fast at import time (not per-request) if ``code`` isn't a known
    permission — catches typos in route definitions during app startup.
    """
    if not is_known_permission(code):
        raise ValueError(f"Unknown permission code: {code!r}")

    async def _check(
        auth: Annotated[AuthContext, Depends(get_active_auth)],
        session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> AuthContext:
        if not auth.has_permission(code):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission: {code}",
            )
        # The verification gate lives here rather than on each endpoint:
        # a list of routes to protect is a list somebody forgets to add
        # to, and the failure mode is a feature that silently works
        # before the customer has proved they own the address.
        #
        # Read per request rather than carried in the token. A claim
        # would mean a customer who has just verified still cannot act
        # until they sign out and back in, which is exactly the moment
        # they are least willing to.
        if auth.company_id is not None and is_blocked_before_verification(code):
            company = await session.get(Company, auth.company_id)
            if company is not None and company.verified_at is None:
                raise EmailNotVerifiedError
        return auth

    return _check


async def enforce_search_rate_limit(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    redis: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> AuthContext:
    """Per-*user* rate limit for global search — same reasoning as
    ``enforce_ai_rate_limit`` below (several agents can share one office
    IP, so per-IP would be wrong), but for a different cost: one search
    fans out across up to nine tables, every one of them a leading-
    wildcard ``ILIKE`` that can't use a btree index. A typeahead firing
    on every keystroke would be genuinely expensive, so this backstops
    the frontend's own debounce rather than trusting it.

    Deliberately depends on ``get_current_auth``, not
    ``require_permission(...)``: one search spans nine entity types with
    nine different permissions, and ``SearchService`` filters per type
    against the caller's own set — see its docstring.
    """
    limiter = FixedWindowRateLimiter(
        redis,
        scope="search",
        limit=settings.search_rate_limit_per_minute,
        window_seconds=60,
    )
    await enforce_rate_limit(limiter, str(auth.user_id))
    return auth


async def enforce_ai_rate_limit(
    auth: Annotated[AuthContext, Depends(require_permission("ai.use"))],
    redis: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuthContext:
    """Per-*user* (not per-IP) rate limit for every ``/ai/*`` endpoint —
    unlike ``core/rate_limit.py``'s pre-auth limiters (login, register,
    webchat sessions), every AI Engine call has a real external cost, so
    it's throttled per authenticated identity rather than per client IP
    (several agents can legitimately share one office IP). Lives here,
    not in ``core/rate_limit.py``, because it needs ``AuthContext`` —
    core/ must not depend on api/.

    Also enforces the company-level AI master switch
    (``Company.settings["ai"]["enabled"]``, default on) — a company can
    disable AI features entirely (e.g. a compliance-sensitive customer)
    even when the platform itself has a provider configured. Every
    ``/ai/*`` endpoint depends on this one function, so this is the
    single choke point for that check — see
    ``docs/architecture/company-onboarding.md``.
    """
    company = await CompanyRepository(session).get_by_id(auth.company_id)
    if company is None or not is_ai_enabled(company.settings):
        raise AiNotConfiguredError()
    limiter = FixedWindowRateLimiter(
        redis, scope="ai", limit=settings.ai_rate_limit_per_minute, window_seconds=60
    )
    await enforce_rate_limit(limiter, str(auth.user_id))
    return auth


async def enforce_channel_test_connection_rate_limit(
    auth: Annotated[AuthContext, Depends(require_permission("channels.manage"))],
    redis: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> AuthContext:
    """Same reasoning as ``enforce_ai_rate_limit``, applied to "Test
    Connection" (both the saved-channel and ephemeral/draft-credentials
    variants) — each call makes the server originate a real outbound
    connection to an operator-chosen host/port, confirmed during Phase 1's
    review as an otherwise-unthrottled internal-network probe/oracle for
    any ``channels.manage`` principal."""
    limiter = FixedWindowRateLimiter(
        redis,
        scope="channel-test-connection",
        limit=settings.channel_test_connection_rate_limit_per_minute,
        window_seconds=60,
    )
    await enforce_rate_limit(limiter, str(auth.user_id))
    return auth


async def enforce_erp_test_connection_rate_limit(
    auth: Annotated[AuthContext, Depends(require_permission("erp.manage"))],
    redis: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> AuthContext:
    """Same reasoning as ``enforce_channel_test_connection_rate_limit``,
    applied to ERP's "Test Connection" — the company-level ERP-enabled
    gate itself lives in ``ErpConfigService``, not here, since that
    service is also used by every other ``erp-configs`` endpoint."""
    limiter = FixedWindowRateLimiter(
        redis,
        scope="erp-test-connection",
        limit=settings.erp_test_connection_rate_limit_per_minute,
        window_seconds=60,
    )
    await enforce_rate_limit(limiter, str(auth.user_id))
    return auth


async def enforce_platform_test_connection_rate_limit(
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    redis: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> PlatformContext:
    """Same reasoning as the channel and ERP connection tests, applied to
    the platform mail test: it makes the server originate an outbound
    connection to an operator-chosen host and port.

    Rate-limited even though the caller is a platform administrator.
    Trusting the operator is not the point — a stolen platform token
    should not turn this installation into a port scanner.
    """
    limiter = FixedWindowRateLimiter(
        redis,
        scope="platform-test-connection",
        limit=settings.erp_test_connection_rate_limit_per_minute,
        window_seconds=60,
    )
    await enforce_rate_limit(limiter, str(platform.user_id))
    return platform


def get_verification_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> VerificationService:
    return VerificationService(
        session=session,
        settings=settings,
        platform_settings=PlatformSettingsService(
            repository=PlatformSettingsRepository(session), settings=settings
        ),
    )


def get_platform_user_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
    refresh_tokens: Annotated[RefreshTokenStore, Depends(get_refresh_token_store)],
    verification: Annotated[VerificationService, Depends(get_verification_service)],
) -> PlatformUserService:
    """Platform administration of a tenant's user accounts.

    Takes the same ``VerificationService`` the self-service resend
    endpoint uses, rather than a console-only copy: there is one
    verification-token issuer in this application, it stores only the
    hash, and a second one would be a second chance to get that wrong.
    """
    return PlatformUserService(
        session=session,
        companies=CompanyRepository(session),
        users=UserRepository(session),
        roles=RoleRepository(session),
        verification=verification,
        refresh_tokens=refresh_tokens,
        events=events,
    )


#: The methods that only read. Everything else changes something and is
#: refused to a read-only operator.
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

#: POSTs that write nothing.
#:
#: A method is a good proxy for "does this change anything" and not a
#: perfect one. These two ask the pricing engine a question whose input is
#: too big for a query string: what does this company resolve to, and what
#: would these terms charge. Both are exactly what read access is *for* —
#: an auditor checking a customer's price, an operator modelling a change
#: they cannot make — and the editor's live preview calls one of them on
#: every keystroke.
#:
#: Named individually rather than inferred from a prefix or a verb, because
#: this list is the one place where "POST" stops meaning "write": every
#: entry has to be argued for, and anything not listed is refused. The safe
#: direction is the default.
#:
#: Identified by *endpoint function*, not by URL path. This used to hold
#: path templates matched against ``request.scope["route"].path``, which was
#: correct until FastAPI 0.141 restructured ``include_router`` to nest
#: routers instead of flattening their routes into the application. After
#: that change ``route.path`` is the path the route was registered with —
#: relative to its own router — while these entries are absolute, so nothing
#: matched and every one of these previews was refused to the operators they
#: exist for. It failed closed, which is the right direction to fail, and is
#: also why nobody noticed it from the outside.
#:
#: A function identity cannot be crafted from a URL and does not move when a
#: router is remounted under a different prefix, so this is strictly stronger
#: than the template matching it replaces — it keeps the property the old
#: comment claimed ("an id in the path can never be crafted to look like an
#: allowlisted route") without depending on how paths are assembled.
#:
#: Written as dotted strings rather than imported callables because
#: ``deps`` is imported *by* every endpoint module; importing them back here
#: is a cycle. ``verify_read_only_allowlist`` resolves these against the
#: real routing table at start-up, so a typo or a renamed endpoint fails
#: loudly at boot rather than silently denying an operator forever.
_READ_ONLY_SAFE_POST_ENDPOINTS = frozenset(
    {
        "blinkengage.api.v1.endpoints.platform_pricing.resolve_usage_price",
        "blinkengage.api.v1.endpoints.platform_pricing.quote_pricing",
        # A POST only because the selection is a list, which does not belong
        # in a query string. It writes nothing, and a read-only operator
        # answering "how much would crediting these lines come to?" is
        # exactly the reading this account exists for.
        "blinkengage.api.v1.endpoints.platform_invoicing.preview_credit_note",
    }
)


def endpoint_identity(route: object) -> str | None:
    """The dotted name of the function a route dispatches to.

    ``None`` for anything without an endpoint (a Mount, a WebSocket route,
    or a router node), which never matches the allowlist — the safe answer.
    """
    endpoint = getattr(route, "endpoint", None)
    if endpoint is None:
        return None
    module = getattr(endpoint, "__module__", None)
    qualname = getattr(endpoint, "__qualname__", None)
    if not module or not qualname:
        return None
    return f"{module}.{qualname}"


_READ_ONLY_DETAIL = (
    "This platform account has read-only access. It can view everything here, "
    "including the full financial history, but not change it."
)


async def require_platform_write(
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
) -> PlatformContext:
    """Refuses an operator who may look but not change.

    Applied per route where a router mixes reads and writes and the gate
    should be visible in the signature. For a whole router, prefer
    ``deny_read_only_writes`` — see why there.
    """
    if platform.read_only:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_READ_ONLY_DETAIL)
    return platform


async def deny_read_only_writes(
    request: Request,
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
) -> None:
    """Read-only means read-only, for every route on this router.

    Declared once at router construction and keyed on the HTTP method, so a
    new POST added to a gated router **inherits the gate** rather than
    shipping unguarded because whoever added it did not think about the
    read-only tier. That is the same principle ``api/v1/router.py`` applies
    to platform authority itself, and it is the difference that matters:
    twenty-one hand-applied decorators are twenty-one chances to forget, and
    the twenty-second route is the one that suspends a customer.

    Before this existed a read-only operator could write off an invoice,
    post a ledger adjustment, run the collections sweep and suspend a
    company. Nothing in the console offered those actions, which is why it
    went unnoticed — a disabled button is a courtesy, not a permission, and
    the console is about to render every one of them.
    """
    if not platform.read_only:
        return
    if request.method in _SAFE_METHODS:
        return
    # Matched on the endpoint function, not on any form of the URL — see
    # _READ_ONLY_SAFE_POST_ENDPOINTS for why this is not a path comparison.
    route = request.scope.get("route")
    if endpoint_identity(route) in _READ_ONLY_SAFE_POST_ENDPOINTS:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_READ_ONLY_DETAIL)


def verify_read_only_allowlist(app: object) -> None:
    """Every allowlisted endpoint must actually be routed.

    An entry that resolves to nothing is indistinguishable at run time from
    an entry that is simply never requested: the gate denies, the operator
    is refused, and no error is raised anywhere. That is exactly the failure
    the FastAPI 0.141 routing change produced, and it went unseen because a
    silent denial looks like a working permission check.

    Called from application start-up so a rename, a typo, or another routing
    restructure is a boot failure — loud, immediate, and before any operator
    is quietly locked out of a preview they are entitled to.
    """
    routed: set[str] = set()

    def walk(routes: Iterable[Any] | None) -> None:
        for route in routes or ():
            identity = endpoint_identity(route)
            if identity is not None:
                routed.add(identity)
            # FastAPI nests included routers; the children live behind
            # `routes` on plain routers and `original_router` on the
            # `_IncludedRouter` wrapper introduced in 0.141.
            walk(getattr(route, "routes", None))
            nested = getattr(route, "original_router", None)
            if nested is not None:
                walk(getattr(nested, "routes", None))

    walk(getattr(app, "routes", None))

    missing = sorted(_READ_ONLY_SAFE_POST_ENDPOINTS - routed)
    if missing:
        raise RuntimeError(
            "read-only allowlist names endpoints that are not routed: "
            f"{missing}. They would be refused to read-only operators with "
            "no error raised anywhere. Fix the names or remove the entries."
        )


async def get_media_company_id(
    conversation_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> UUID:
    """Which tenant a signed media request concerns.

    Read from the conversation rather than taken from the URL. A signed
    media link deliberately carries no identity — see
    ``core/media_tokens.py`` — and putting a company id in the query string
    would mean the signature was verified against a value the *caller*
    supplied. Resolving it from the row instead means a token minted for one
    tenant cannot verify against another's attachment even if the
    attachment id were known.
    """
    from blinkengage.infrastructure.database.models.conversation import Conversation

    company_id = (
        await session.execute(
            select(Conversation.company_id).where(Conversation.id == conversation_id)
        )
    ).scalar_one_or_none()
    if company_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return company_id


def get_platform_settings_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> PlatformSettingsService:
    return PlatformSettingsService(
        repository=PlatformSettingsRepository(session), settings=settings
    )


def get_tool_services(
    departments: Annotated[DepartmentService, Depends(get_department_service)],
    teams: Annotated[TeamService, Depends(get_team_service)],
    agents: Annotated[AgentService, Depends(get_agent_service)],
    roles: Annotated[RoleService, Depends(get_role_service)],
    knowledge_records: Annotated[KnowledgeRecordService, Depends(get_knowledge_record_service)],
) -> ToolServices:
    """The closed set of services an AI tool handler may reach.

    Assembled here from the same providers the REST endpoints use, so a
    tool and the equivalent hand-driven request go through identical
    business logic. Note what is absent: no session, no repository, no
    container — a handler has no expression available for reaching past
    these five.
    """
    return ToolServices(
        departments=departments,
        teams=teams,
        agents=agents,
        roles=roles,
        knowledge_records=knowledge_records,
    )


def get_tool_context(
    auth: Annotated[AuthContext, Depends(get_active_auth)],
    services: Annotated[ToolServices, Depends(get_tool_services)],
) -> ToolContext:
    """Identity for a tool call, from the request — never from the model."""
    return ToolContext(auth=auth, services=services, correlation_id=get_correlation_id())


def get_tool_executor(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> ToolExecutor:
    return ToolExecutor(
        registry=DEFAULT_REGISTRY, session=session, idempotency=IdempotencyStore(redis)
    )
