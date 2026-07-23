"""Import every ORM model module so ``Base.metadata`` is fully populated.

Alembic's ``env.py`` imports this package before running/autogenerating
migrations; test fixtures that call ``Base.metadata.create_all`` rely on
the same side effect.
"""

from blinkengage.infrastructure.database.models.agent import Agent, AgentStatus
from blinkengage.infrastructure.database.models.audit_log import AuditLog
from blinkengage.infrastructure.database.models.channel_config import ChannelConfig
from blinkengage.infrastructure.database.models.company import Company
from blinkengage.infrastructure.database.models.conversation import (
    Conversation,
    ConversationStatus,
)
from blinkengage.infrastructure.database.models.customer import Customer, CustomerTag, Tag
from blinkengage.infrastructure.database.models.customer_channel_identity import (
    CustomerChannelIdentity,
)
from blinkengage.infrastructure.database.models.department import Department
from blinkengage.infrastructure.database.models.event_outbox import EventOutbox
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
from blinkengage.infrastructure.database.models.queue import (
    AgentSkill,
    AgentSkillAssignment,
    Queue,
    QueueAssignmentStrategy,
    QueueRequiredSkill,
    RoutingRule,
)
from blinkengage.infrastructure.database.models.rbac import (
    Permission,
    Role,
    RolePermission,
    UserRole,
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
    "AgentSkill",
    "AgentSkillAssignment",
    "AgentStatus",
    "AttachmentValidationStatus",
    "AuditLog",
    "ChannelConfig",
    "Company",
    "Conversation",
    "ConversationStatus",
    "Customer",
    "CustomerChannelIdentity",
    "CustomerTag",
    "DeliveryStatus",
    "Department",
    "EventOutbox",
    "Message",
    "MessageAttachment",
    "MessageDirection",
    "MessageStatus",
    "MessageType",
    "Permission",
    "Queue",
    "QueueAssignmentStrategy",
    "QueueRequiredSkill",
    "ReadStatus",
    "Role",
    "RolePermission",
    "RoutingRule",
    "Tag",
    "Team",
    "TeamMembership",
    "User",
    "UserRole",
    "WorkflowDefinition",
    "WorkflowRun",
    "WorkflowRunStatus",
]
