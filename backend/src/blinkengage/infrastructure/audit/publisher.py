"""Concrete ``AuditPublisher`` — persists an ``AuditEvent`` as an ``AuditLog``
row via the repository, on whatever ``AsyncSession`` the caller is already
using. See ``domain.audit`` for why this is synchronous and in-transaction
rather than queued.
"""

from blinkengage.domain.audit import AuditEvent
from blinkengage.infrastructure.database.models.audit_log import AuditLog
from blinkengage.infrastructure.repositories.audit_log_repository import AuditLogRepository


class AuditLogPublisher:
    """Structurally satisfies ``domain.audit.AuditPublisher``."""

    def __init__(self, audit_logs: AuditLogRepository) -> None:
        self._audit_logs = audit_logs

    async def publish(self, event: AuditEvent) -> None:
        await self._audit_logs.add(
            AuditLog(
                company_id=event.company_id,
                actor_user_id=event.actor_user_id,
                action=event.action,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                details=event.details,
            )
        )
