from datetime import datetime
from uuid import UUID

from blinkengage.infrastructure.database.models.audit_log import AuditLog
from blinkengage.infrastructure.repositories.audit_log_repository import AuditLogRepository


class AuditLogService:
    """Read-only query side of the audit log.

    Rows are never written here — every write goes through an
    ``AuditPublisher`` (see ``domain.audit``) called directly from the
    service whose action is being audited, in the same transaction.
    """

    def __init__(self, *, audit_logs: AuditLogRepository) -> None:
        self._audit_logs = audit_logs

    async def list_logs(
        self,
        *,
        company_id: UUID,
        offset: int,
        limit: int,
        entity_type: str | None,
        action: str | None,
        actor_user_id: UUID | None,
        entity_id: UUID | None,
        since: datetime | None,
        until: datetime | None,
    ) -> tuple[list[AuditLog], int]:
        return await self._audit_logs.list_for_company(
            company_id=company_id,
            offset=offset,
            limit=limit,
            entity_type=entity_type,
            action=action,
            actor_user_id=actor_user_id,
            entity_id=entity_id,
            since=since,
            until=until,
        )
