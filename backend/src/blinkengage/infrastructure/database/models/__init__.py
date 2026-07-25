"""Import every ORM model module so ``Base.metadata`` is fully populated.

Alembic's ``env.py`` imports this package before running/autogenerating
migrations; test fixtures that call ``Base.metadata.create_all`` rely on
the same side effect.
"""

from blinkengage.infrastructure.database.models.agent import Agent, AgentStatus
from blinkengage.infrastructure.database.models.audit_log import AuditLog
from blinkengage.infrastructure.database.models.channel_config import ChannelConfig
from blinkengage.infrastructure.database.models.channel_connection_log import (
    ChannelConnectionLog,
)
from blinkengage.infrastructure.database.models.company import Company
from blinkengage.infrastructure.database.models.conversation import (
    Conversation,
    ConversationStatus,
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
from blinkengage.infrastructure.database.models.erp import (
    ErpConfig,
    ErpCustomerLink,
    ErpSyncedRecord,
)
from blinkengage.infrastructure.database.models.event_outbox import EventOutbox
from blinkengage.infrastructure.database.models.internal_note import InternalNote
from blinkengage.infrastructure.database.models.knowledge import (
    KnowledgeArticle,
    KnowledgeArticleTag,
    KnowledgeCategory,
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
from blinkengage.infrastructure.database.models.notification import Notification
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
from blinkengage.infrastructure.database.models.team import Team, TeamMembership
from blinkengage.infrastructure.database.models.user import User
from blinkengage.infrastructure.database.models.workflow import (
    WorkflowDefinition,
    WorkflowRun,
    WorkflowRunStatus,
)

__all__ = [
    "Agent",
    "AgentDailyStats",
    "AgentSkill",
    "AgentSkillAssignment",
    "AgentStatus",
    "AiDailyStats",
    "AttachmentValidationStatus",
    "AuditLog",
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
    "ErpConfig",
    "ErpCustomerLink",
    "ErpSyncedRecord",
    "EventOutbox",
    "InternalNote",
    "KnowledgeArticle",
    "KnowledgeArticleTag",
    "KnowledgeCategory",
    "Message",
    "MessageAttachment",
    "MessageDirection",
    "MessageStatus",
    "MessageType",
    "Notification",
    "Permission",
    "Queue",
    "QueueAssignmentStrategy",
    "QueueDailyStats",
    "QueueRequiredSkill",
    "QuickReply",
    "ReadStatus",
    "Role",
    "RolePermission",
    "RoutingRule",
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
