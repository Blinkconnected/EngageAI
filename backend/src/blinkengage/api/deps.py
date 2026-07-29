"""FastAPI dependency providers.

These bridge the DI container to route handlers via ``Depends`` and are the
only place API code touches the container directly.
"""

from collections.abc import AsyncGenerator, Callable, Coroutine
from datetime import timedelta
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import Depends, HTTPException, Query, Request, WebSocket, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from minio import Minio
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.application.services.agent_service import AgentService
from blinkengage.application.services.agent_skill_service import AgentSkillService
from blinkengage.application.services.ai_service import AiService
from blinkengage.application.services.audit_log_service import AuditLogService
from blinkengage.application.services.auth_service import AuthService
from blinkengage.application.services.autopilot_service import AutopilotService
from blinkengage.application.services.billing_service import BillingService
from blinkengage.application.services.channel_config_service import ChannelConfigService
from blinkengage.application.services.company_service import CompanyService
from blinkengage.application.services.conversation_service import ConversationService
from blinkengage.application.services.csat_service import CsatService
from blinkengage.application.services.customer_internal_rating_service import (
    CustomerInternalRatingService,
)
from blinkengage.application.services.customer_service import CustomerService
from blinkengage.application.services.department_service import DepartmentService
from blinkengage.application.services.erp_config_service import ErpConfigService
from blinkengage.application.services.erp_sync_service import ErpSyncService
from blinkengage.application.services.feature_service import FeatureService
from blinkengage.application.services.internal_note_service import InternalNoteService
from blinkengage.application.services.knowledge_service import KnowledgeService
from blinkengage.application.services.notification_preference_service import (
    NotificationPreferenceService,
)
from blinkengage.application.services.notification_service import NotificationService
from blinkengage.application.services.platform_service import PlatformService
from blinkengage.application.services.queue_service import QueueService
from blinkengage.application.services.quick_reply_service import QuickReplyService
from blinkengage.application.services.reporting_service import ReportingService
from blinkengage.application.services.role_service import RoleService
from blinkengage.application.services.routing_rule_service import RoutingRuleService
from blinkengage.application.services.search_service import SearchService
from blinkengage.application.services.sla_policy_service import SlaPolicyService
from blinkengage.application.services.team_service import TeamService
from blinkengage.application.services.web_chat_session_service import WebChatSessionService
from blinkengage.application.services.webhook_ingest_service import WebhookIngestService
from blinkengage.application.services.workflow_service import WorkflowService
from blinkengage.core.auth_context import AuthContext, PlatformContext
from blinkengage.core.config import Settings
from blinkengage.core.container import Container
from blinkengage.core.rate_limit import FixedWindowRateLimiter, enforce_rate_limit
from blinkengage.core.security import InvalidTokenError, TokenType, decode_token
from blinkengage.domain.ai_provider import AiProvider
from blinkengage.domain.company_settings import is_ai_enabled
from blinkengage.domain.exceptions import AiNotConfiguredError
from blinkengage.domain.features import FEATURES, is_known_feature
from blinkengage.domain.rbac import is_known_permission
from blinkengage.infrastructure.ai.factory import build_ai_provider_for_company
from blinkengage.infrastructure.billing.paypal_client import PayPalClient
from blinkengage.infrastructure.cache.chat_session_store import ChatSessionStore
from blinkengage.infrastructure.cache.refresh_tokens import RefreshTokenStore
from blinkengage.infrastructure.channels.factory import ChannelProviderFactory
from blinkengage.infrastructure.database.models.company import CompanyStatus
from blinkengage.infrastructure.database.models.user import User
from blinkengage.infrastructure.events.outbox_publisher import OutboxEventPublisher
from blinkengage.infrastructure.events.realtime_publisher import RealtimePublisher
from blinkengage.infrastructure.repositories.agent_repository import AgentRepository
from blinkengage.infrastructure.repositories.agent_skill_repository import AgentSkillRepository
from blinkengage.infrastructure.repositories.audit_log_repository import AuditLogRepository
from blinkengage.infrastructure.repositories.billing_repository import (
    BillingPlanRepository,
    PaymentRepository,
    SubscriptionRepository,
    WebhookEventRepository,
)
from blinkengage.infrastructure.repositories.channel_config_repository import (
    ChannelConfigRepository,
)
from blinkengage.infrastructure.repositories.channel_connection_log_repository import (
    ChannelConnectionLogRepository,
)
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
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
from blinkengage.infrastructure.repositories.holiday_repository import HolidayRepository
from blinkengage.infrastructure.repositories.internal_note_repository import (
    InternalNoteRepository,
)
from blinkengage.infrastructure.repositories.knowledge_repository import (
    KnowledgeArticleRepository,
    KnowledgeCategoryRepository,
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
from blinkengage.infrastructure.repositories.platform_repository import PlatformRepository
from blinkengage.infrastructure.repositories.queue_repository import QueueRepository
from blinkengage.infrastructure.repositories.quick_reply_repository import QuickReplyRepository
from blinkengage.infrastructure.repositories.reporting_repository import ReportingRepository
from blinkengage.infrastructure.repositories.role_repository import RoleRepository
from blinkengage.infrastructure.repositories.routing_rule_repository import (
    RoutingRuleRepository,
)
from blinkengage.infrastructure.repositories.search_repository import SearchRepository
from blinkengage.infrastructure.repositories.sla_policy_repository import SlaPolicyRepository
from blinkengage.infrastructure.repositories.tag_repository import TagRepository
from blinkengage.infrastructure.repositories.team_repository import TeamRepository
from blinkengage.infrastructure.repositories.user_repository import UserRepository
from blinkengage.infrastructure.repositories.workflow_repository import (
    WorkflowDefinitionRepository,
)
from blinkengage.infrastructure.repositories.workflow_run_repository import (
    WorkflowRunRepository,
)
from blinkengage.infrastructure.storage.attachment_store import AttachmentStore

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
    return PlatformContext(user_id=user.id)


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


def get_conversation_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    attachment_store: Annotated[AttachmentStore, Depends(get_attachment_store)],
    provider_factory: Annotated[ChannelProviderFactory, Depends(get_channel_provider_factory)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
    realtime: Annotated[RealtimePublisher, Depends(get_realtime_publisher)],
) -> ConversationService:
    return ConversationService(
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


def get_conversation_service_ws(
    session: Annotated[AsyncSession, Depends(get_db_session_ws)],
    settings: Annotated[Settings, Depends(get_settings_dep_ws)],
    attachment_store: Annotated[AttachmentStore, Depends(get_attachment_store_ws)],
    provider_factory: Annotated[ChannelProviderFactory, Depends(get_channel_provider_factory_ws)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher_ws)],
    realtime: Annotated[RealtimePublisher, Depends(get_realtime_publisher_ws)],
) -> ConversationService:
    return ConversationService(
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


def get_queue_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
) -> QueueService:
    return QueueService(
        queues=QueueRepository(session),
        agent_skills=AgentSkillRepository(session),
        sla_policies=SlaPolicyRepository(session),
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


def get_notification_preference_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> NotificationPreferenceService:
    return NotificationPreferenceService(preferences=NotificationPreferenceRepository(session))


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


def get_billing_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
) -> BillingService:
    """Builds the billing service, with a PayPal client only if this
    installation is actually configured for it.

    ``paypal=None`` is a first-class state, not an error: an installation
    that does not sell subscriptions must still start, and every billing
    endpoint must still answer. The service turns that into a clear
    "billing is not configured" (503) or an ``is_configured: false`` in
    the overview, rather than a crash at import time or a 500 at call
    time.
    """
    paypal = (
        PayPalClient(
            client_id=settings.paypal_client_id,
            client_secret=settings.paypal_client_secret,
            environment=settings.paypal_environment,
        )
        if settings.paypal_client_id and settings.paypal_client_secret
        else None
    )
    return BillingService(
        plans=BillingPlanRepository(session),
        subscriptions=SubscriptionRepository(session),
        payments=PaymentRepository(session),
        webhook_events=WebhookEventRepository(session),
        companies=CompanyRepository(session),
        events=events,
        settings=settings,
        paypal=paypal,
    )


#: Feature keys to their human names, so a 402 says "AI Engine is not
#: included in this workspace's plan" rather than repeating a slug at
#: somebody who never chose it.
_FEATURE_NAMES: dict[str, str] = {feature.key: feature.name for feature in FEATURES}


def get_feature_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
) -> FeatureService:
    return FeatureService(
        companies=CompanyRepository(session),
        subscriptions=SubscriptionRepository(session),
        plans=BillingPlanRepository(session),
        events=events,
    )


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
                    f"{_FEATURE_NAMES.get(key, key)} is not included in this workspace's plan. "
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
                f"{_FEATURE_NAMES['reports_export']} is not included in this workspace's plan. "
                "Contact your provider to enable it."
            ),
        )


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
) -> Callable[[AuthContext], Coroutine[Any, Any, AuthContext]]:
    """Dependency factory: ``Depends(require_permission("customers.manage"))``.

    Fails fast at import time (not per-request) if ``code`` isn't a known
    permission — catches typos in route definitions during app startup.
    """
    if not is_known_permission(code):
        raise ValueError(f"Unknown permission code: {code!r}")

    async def _check(auth: Annotated[AuthContext, Depends(get_active_auth)]) -> AuthContext:
        if not auth.has_permission(code):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission: {code}",
            )
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
