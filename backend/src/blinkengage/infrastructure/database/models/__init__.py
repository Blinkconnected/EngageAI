"""Import every ORM model module so ``Base.metadata`` is fully populated.

Alembic's ``env.py`` imports this package before running/autogenerating
migrations; test fixtures that call ``Base.metadata.create_all`` rely on
the same side effect.
"""

from blinkengage.infrastructure.database.models.agent import Agent, AgentStatus
from blinkengage.infrastructure.database.models.ai_action import AiActionLog, PendingAiAction
from blinkengage.infrastructure.database.models.ai_assistant_turn import AiAssistantTurn
from blinkengage.infrastructure.database.models.audit_log import AuditLog
from blinkengage.infrastructure.database.models.billable_event import BillableEvent
from blinkengage.infrastructure.database.models.billing_summary import (
    BillingDailySummary,
)
from blinkengage.infrastructure.database.models.channel_config import ChannelConfig
from blinkengage.infrastructure.database.models.channel_connection_log import (
    ChannelConnectionLog,
)
from blinkengage.infrastructure.database.models.collections import DunningNotice
from blinkengage.infrastructure.database.models.company import Company
from blinkengage.infrastructure.database.models.conversation import (
    Conversation,
    ConversationStatus,
)
from blinkengage.infrastructure.database.models.conversation_deletion_request import (
    ConversationDeletionRequest,
)
from blinkengage.infrastructure.database.models.conversation_transfer import (
    ConversationTransfer,
    TransferTargetType,
)
from blinkengage.infrastructure.database.models.customer import Customer, CustomerTag, Tag
from blinkengage.infrastructure.database.models.customer_channel_identity import (
    CustomerChannelIdentity,
)
from blinkengage.infrastructure.database.models.department import Department
from blinkengage.infrastructure.database.models.device_token import DeviceToken
from blinkengage.infrastructure.database.models.embedding import (
    OWNER_KNOWLEDGE_CHUNK,
    Embedding,
    KnowledgeChunk,
    KnowledgeIndexState,
)
from blinkengage.infrastructure.database.models.erp import (
    ErpConfig,
    ErpCustomerLink,
    ErpSyncedRecord,
)
from blinkengage.infrastructure.database.models.event_outbox import EventOutbox
from blinkengage.infrastructure.database.models.faq import (
    Faq,
    FaqTag,
)
from blinkengage.infrastructure.database.models.financial_audit import FinancialAuditEvent
from blinkengage.infrastructure.database.models.internal_note import InternalNote
from blinkengage.infrastructure.database.models.invoicing import (
    CreditNote,
    CreditNoteLine,
    DocumentNumberSequence,
    Invoice,
    InvoiceLine,
    Payment,
    PaymentAllocation,
)
from blinkengage.infrastructure.database.models.knowledge import (
    KnowledgeArticle,
    KnowledgeArticleTag,
    KnowledgeCategory,
)
from blinkengage.infrastructure.database.models.knowledge_record import (
    KnowledgeRecord,
)
from blinkengage.infrastructure.database.models.knowledge_source import (
    KnowledgeDocument,
    KnowledgeIngestionJob,
    KnowledgeSenderAllowlistEntry,
    KnowledgeSourceMessage,
)
from blinkengage.infrastructure.database.models.learning import (
    RUN_TYPE_OBSERVATION,
    RUN_TYPE_SETTLE,
    LearningObservation,
    LearningObservationFeature,
    LearningObservationRef,
    LearningRun,
)
from blinkengage.infrastructure.database.models.learning_analysis import (
    RUN_TYPE_ANALYSIS,
    RUN_TYPE_CLUSTER,
    LearningAnomaly,
    LearningCluster,
    LearningClusterMember,
    LearningTrend,
)
from blinkengage.infrastructure.database.models.ledger import LedgerEntry
from blinkengage.infrastructure.database.models.memory import (
    OWNER_MEMORY_FACT,
    MemoryConfidenceSample,
    MemoryContradiction,
    MemoryEvidence,
    MemoryFact,
)
from blinkengage.infrastructure.database.models.message import (
    AttachmentValidationStatus,
    DeliveryStatus,
    Message,
    MessageAttachment,
    MessageDirection,
    MessageStatus,
    MessageType,
    ReadStatus,
)
from blinkengage.infrastructure.database.models.message_redaction import MessageRedaction
from blinkengage.infrastructure.database.models.notification import Notification
from blinkengage.infrastructure.database.models.notification_preference import (
    NotificationPreference,
)
from blinkengage.infrastructure.database.models.ownership import ConversationOwnership
from blinkengage.infrastructure.database.models.payments import (
    PaymentIntent,
    PaymentRefund,
)
from blinkengage.infrastructure.database.models.platform_settings import (
    PlatformSetting,
)
from blinkengage.infrastructure.database.models.pricing import (
    CompanyPricingProfileAssignment,
    PricingAuditLog,
    PricingProfile,
    PricingRate,
)
from blinkengage.infrastructure.database.models.queue import (
    AgentSkill,
    AgentSkillAssignment,
    Queue,
    QueueAssignmentStrategy,
    QueueRequiredSkill,
    RoutingRule,
)
from blinkengage.infrastructure.database.models.quick_reply import QuickReply
from blinkengage.infrastructure.database.models.rbac import (
    Permission,
    Role,
    RolePermission,
    UserRole,
)
from blinkengage.infrastructure.database.models.reporting import (
    AgentDailyStats,
    AiDailyStats,
    ConversationDailyStats,
    CsatDailyStats,
    CsatResponse,
    QueueDailyStats,
)
from blinkengage.infrastructure.database.models.routing_decision import (
    RoutingDecisionRecord,
)
from blinkengage.infrastructure.database.models.scheduler_run import SchedulerRun
from blinkengage.infrastructure.database.models.service_directory import (
    ConversationContextBinding,
    CustomerContextVersion,
    RuntimeQueue,
    Service,
    ServiceVersion,
)
from blinkengage.infrastructure.database.models.sla import Holiday, SlaPolicy
from blinkengage.infrastructure.database.models.sla_clock import ConversationSlaClock
from blinkengage.infrastructure.database.models.team import Team, TeamMembership
from blinkengage.infrastructure.database.models.usage import (
    BillingPeriod,
    UsagePeriodLine,
    UsageRecord,
)
from blinkengage.infrastructure.database.models.user import User
from blinkengage.infrastructure.database.models.verification import (
    EmailVerificationToken,
)
from blinkengage.infrastructure.database.models.workflow import (
    WorkflowDefinition,
    WorkflowRun,
    WorkflowRunStatus,
)

__all__ = [
    "Agent",
    "AiActionLog",
    "AiAssistantTurn",
    "AgentDailyStats",
    "AgentSkill",
    "AgentSkillAssignment",
    "AgentStatus",
    "PendingAiAction",
    "AiDailyStats",
    "AttachmentValidationStatus",
    "AuditLog",
    "BillableEvent",
    "BillingDailySummary",
    "BillingPeriod",
    "CreditNote",
    "FinancialAuditEvent",
    "CreditNoteLine",
    "DocumentNumberSequence",
    "Invoice",
    "InvoiceLine",
    "DunningNotice",
    "EmailVerificationToken",
    "LedgerEntry",
    "Payment",
    "PlatformSetting",
    "PaymentIntent",
    "PaymentRefund",
    "PaymentAllocation",
    "UsagePeriodLine",
    "UsageRecord",
    "CompanyPricingProfileAssignment",
    "PricingAuditLog",
    "PricingProfile",
    "PricingRate",
    "ChannelConfig",
    "ChannelConnectionLog",
    "Company",
    "Conversation",
    "ConversationDailyStats",
    "ConversationStatus",
    "ConversationTransfer",
    "CsatDailyStats",
    "CsatResponse",
    "Customer",
    "CustomerChannelIdentity",
    "CustomerTag",
    "DeliveryStatus",
    "Department",
    "DeviceToken",
    "ErpConfig",
    "ErpCustomerLink",
    "ErpSyncedRecord",
    "EventOutbox",
    "Holiday",
    "InternalNote",
    "OWNER_KNOWLEDGE_CHUNK",
    "ConversationDeletionRequest",
    "MessageRedaction",
    "Embedding",
    "Faq",
    "FaqTag",
    "KnowledgeArticle",
    "KnowledgeArticleTag",
    "KnowledgeCategory",
    "KnowledgeChunk",
    "KnowledgeIndexState",
    "KnowledgeRecord",
    "KnowledgeDocument",
    "KnowledgeIngestionJob",
    "KnowledgeSenderAllowlistEntry",
    "KnowledgeSourceMessage",
    "LearningAnomaly",
    "LearningCluster",
    "LearningClusterMember",
    "LearningObservation",
    "LearningObservationFeature",
    "LearningObservationRef",
    "LearningRun",
    "LearningTrend",
    "RUN_TYPE_ANALYSIS",
    "RUN_TYPE_CLUSTER",
    "RUN_TYPE_OBSERVATION",
    "RUN_TYPE_SETTLE",
    "OWNER_MEMORY_FACT",
    "MemoryConfidenceSample",
    "MemoryContradiction",
    "MemoryEvidence",
    "MemoryFact",
    "Message",
    "MessageAttachment",
    "MessageDirection",
    "MessageStatus",
    "MessageType",
    "Notification",
    "NotificationPreference",
    "Permission",
    "Queue",
    "ConversationContextBinding",
    "ConversationOwnership",
    "ConversationSlaClock",
    "CustomerContextVersion",
    "QueueAssignmentStrategy",
    "QueueDailyStats",
    "QueueRequiredSkill",
    "QuickReply",
    "ReadStatus",
    "Role",
    "RolePermission",
    "RoutingDecisionRecord",
    "RuntimeQueue",
    "SchedulerRun",
    "RoutingRule",
    "Service",
    "ServiceVersion",
    "SlaPolicy",
    "Tag",
    "Team",
    "TeamMembership",
    "TransferTargetType",
    "User",
    "UserRole",
    "WorkflowDefinition",
    "WorkflowRun",
    "WorkflowRunStatus",
]
