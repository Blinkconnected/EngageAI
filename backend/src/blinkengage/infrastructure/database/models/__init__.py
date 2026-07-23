"""Import every ORM model module so ``Base.metadata`` is fully populated.

Alembic's ``env.py`` imports this package before running/autogenerating
migrations; test fixtures that call ``Base.metadata.create_all`` rely on
the same side effect.
"""

from blinkengage.infrastructure.database.models.agent import Agent, AgentStatus
from blinkengage.infrastructure.database.models.audit_log import AuditLog
from blinkengage.infrastructure.database.models.channel_config import ChannelConfig
from blinkengage.infrastructure.database.models.company import Company
from blinkengage.infrastructure.database.models.customer import Customer, CustomerTag, Tag
from blinkengage.infrastructure.database.models.department import Department
from blinkengage.infrastructure.database.models.event_outbox import EventOutbox
from blinkengage.infrastructure.database.models.rbac import (
    Permission,
    Role,
    RolePermission,
    UserRole,
)
from blinkengage.infrastructure.database.models.team import Team, TeamMembership
from blinkengage.infrastructure.database.models.user import User

__all__ = [
    "Agent",
    "AgentStatus",
    "AuditLog",
    "ChannelConfig",
    "Company",
    "Customer",
    "CustomerTag",
    "Department",
    "EventOutbox",
    "Permission",
    "Role",
    "RolePermission",
    "Tag",
    "Team",
    "TeamMembership",
    "User",
    "UserRole",
]
