"""RBAC permission catalog and default role definitions.

This module is pure Python — no framework or persistence dependencies —
so the permission model can be unit tested in isolation and reused by any
layer (API, Celery tasks, CLI tooling) without pulling in SQLAlchemy.

Permission codes follow ``<resource>.<action>``. Every code referenced by
``DEFAULT_ROLE_PERMISSIONS`` must exist in ``PERMISSIONS`` — this is
enforced by a unit test, not just convention.
"""

from dataclasses import dataclass
from enum import StrEnum


class SystemRole(StrEnum):
    """Roles seeded automatically for every new company.

    ``OWNER`` is granted every permission and cannot be deleted or have its
    permissions edited — every company has exactly one company-creation-time
    Owner. ``ADMIN`` and ``AGENT`` are editable, deletable (except their
    permission grants are copyable defaults, not protected), ordinary
    starting points for company administrators to customize.
    """

    OWNER = "Owner"
    ADMIN = "Admin"
    AGENT = "Agent"


@dataclass(frozen=True, slots=True)
class Permission:
    code: str
    description: str


PERMISSIONS: tuple[Permission, ...] = (
    # --- Companies / tenant administration ---
    Permission("company.manage", "Manage company profile and settings"),
    # --- Users & RBAC ---
    Permission("users.read", "View users in the company"),
    Permission("users.manage", "Invite, edit, deactivate users"),
    Permission("roles.manage", "Create/edit/delete roles and their permissions"),
    # --- Directory: departments, teams, agents ---
    Permission("departments.read", "View departments"),
    Permission("departments.manage", "Create/edit/delete departments"),
    Permission("teams.read", "View teams"),
    Permission("teams.manage", "Create/edit/delete teams"),
    Permission("agents.read", "View agent profiles"),
    Permission("agents.manage", "Create/edit/delete agent profiles"),
    # --- Customers ---
    Permission("customers.read", "View customer profiles"),
    Permission("customers.manage", "Create/edit/merge/delete customer profiles"),
    # --- Conversations ---
    Permission("conversations.read", "View conversations"),
    Permission("conversations.manage", "Reply, assign, close conversations"),
    Permission("conversations.delete", "Permanently delete conversations"),
    # --- Reporting ---
    Permission("reports.read", "View reports and dashboards"),
    # --- Audit ---
    Permission("audit_logs.read", "View audit logs"),
    # --- Channels (see docs/architecture/channels.md) ---
    Permission("channels.read", "View channel configurations"),
    Permission("channels.manage", "Create/edit/delete channel configurations"),
    # --- Queues, skills, routing (see docs/architecture/queues-routing.md) ---
    Permission("queues.read", "View queues, required skills, and routing rules"),
    Permission("queues.manage", "Create/edit/delete queues, required skills, and routing rules"),
    # --- Workflow Engine (see docs/architecture/workflow-engine.md) ---
    Permission("workflows.read", "View workflow definitions and their run history"),
    Permission("workflows.manage", "Create/edit/delete workflow definitions"),
    # --- Knowledge Base / Quick Replies (see
    # docs/architecture/knowledge-quick-replies-notes.md) — internal notes
    # reuse conversations.read/manage rather than a new permission, since
    # a note is just another way to interact with a conversation the
    # agent already has access to. ---
    Permission("knowledge_base.read", "View knowledge base categories and articles"),
    Permission(
        "knowledge_base.manage", "Create/edit/delete knowledge base categories and articles"
    ),
    Permission("quick_replies.read", "View quick replies"),
    Permission("quick_replies.manage", "Create/edit/delete quick replies"),
)

_PERMISSION_CODES: frozenset[str] = frozenset(p.code for p in PERMISSIONS)

DEFAULT_ROLE_PERMISSIONS: dict[SystemRole, frozenset[str]] = {
    SystemRole.OWNER: _PERMISSION_CODES,
    SystemRole.ADMIN: frozenset(
        {
            "users.read",
            "users.manage",
            "departments.read",
            "departments.manage",
            "teams.read",
            "teams.manage",
            "agents.read",
            "agents.manage",
            "customers.read",
            "customers.manage",
            "conversations.read",
            "conversations.manage",
            "reports.read",
            "audit_logs.read",
            "channels.read",
            "channels.manage",
            "queues.read",
            "queues.manage",
            "workflows.read",
            "workflows.manage",
            "knowledge_base.read",
            "knowledge_base.manage",
            "quick_replies.read",
            "quick_replies.manage",
        }
    ),
    SystemRole.AGENT: frozenset(
        {
            "departments.read",
            "teams.read",
            "agents.read",
            "customers.read",
            "customers.manage",
            "conversations.read",
            "conversations.manage",
            "reports.read",
            "queues.read",
            "workflows.read",
            "knowledge_base.read",
            "quick_replies.read",
        }
    ),
}


def is_known_permission(code: str) -> bool:
    return code in _PERMISSION_CODES


def resolve_effective_permissions(role_permission_codes: list[frozenset[str]]) -> frozenset[str]:
    """Union the permission sets of every role assigned to a user."""
    effective: set[str] = set()
    for codes in role_permission_codes:
        effective |= codes
    return frozenset(effective)
