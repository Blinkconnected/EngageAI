"""Audit event contract.

Application services publish an ``AuditEvent`` after every state-changing
operation. The publisher persists it in the *same* database transaction as
the triggering change (see ``infrastructure.audit.publisher``) so an audit
entry can never be silently lost to a later rollback, and a committed
business change can never end up missing its audit trail.

This is intentionally a direct call from each service, not a general-purpose
in-process event bus with multiple subscribers — there is exactly one
consumer (the audit log) today, and adding indirection for a single consumer
would be speculative.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """A single auditable occurrence.

    ``action`` follows a ``<entity_type>.<verb>`` convention, e.g.
    ``"department.created"``. ``actor_user_id`` is ``None`` only for events
    with no authenticated actor (there are none yet, but the column and this
    field stay nullable for future system-initiated events).
    """

    company_id: UUID
    action: str
    entity_type: str
    entity_id: UUID | None
    actor_user_id: UUID | None = None
    details: dict[str, Any] = field(default_factory=dict)


class AuditPublisher(Protocol):
    async def publish(self, event: AuditEvent) -> None: ...


__all__ = ["AuditEvent", "AuditPublisher"]
