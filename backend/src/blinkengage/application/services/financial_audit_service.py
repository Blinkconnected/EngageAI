"""Recording the financial audit trail.

See ``docs/architecture/billing.md``.

Deliberately a small, dependency-light recorder rather than a service
with behaviour of its own: it is called from inside every financial
operation, on the **same session**, so the audit row commits with the
change it describes or neither exists. An audit trail written on a
separate connection, or published through a broker, is one that can
disagree with the thing it is recording — and a trail that disagrees is
worse than none, because it will be believed.

The correlation ID is read from ambient context rather than passed in,
so every event produced by one logical action shares it without each
call site having to remember.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from blinkengage.core.correlation import get_correlation_id
from blinkengage.domain.financial_audit import FinancialEntityType, FinancialEventType
from blinkengage.infrastructure.database.models.financial_audit import FinancialAuditEvent
from blinkengage.infrastructure.repositories.financial_audit_repository import (
    FinancialAuditRepository,
)


@dataclass(frozen=True, slots=True)
class AuditActor:
    """Who did it.

    ``system`` is a distinct answer from "unknown": a scheduled overdue
    sweep genuinely has no human behind it, and recording that honestly
    is more useful than a NULL that could mean either.
    """

    user_id: uuid.UUID | None = None
    email: str | None = None
    name: str | None = None
    system: bool = False

    @classmethod
    def system_actor(cls, name: str = "System") -> "AuditActor":
        return cls(system=True, name=name)


class FinancialAuditRecorder:
    def __init__(self, repository: FinancialAuditRepository) -> None:
        self._repository = repository

    async def record(
        self,
        *,
        event_type: FinancialEventType,
        entity_type: FinancialEntityType,
        entity_id: uuid.UUID,
        actor: AuditActor,
        company_id: uuid.UUID | None = None,
        previous_state: str | None = None,
        new_state: str | None = None,
        amount: Decimal | None = None,
        currency: str | None = None,
        reason: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> FinancialAuditEvent:
        return await self._repository.add(
            FinancialAuditEvent(
                event_type=event_type.value,
                entity_type=entity_type.value,
                entity_id=entity_id,
                company_id=company_id,
                previous_state=previous_state,
                new_state=new_state,
                amount=amount,
                currency=currency,
                actor_user_id=actor.user_id,
                actor_email=actor.email,
                actor_name=actor.name,
                actor_is_system=actor.system,
                correlation_id=get_correlation_id(),
                reason=reason,
                details=dict(details or {}),
            )
        )


__all__ = ["AuditActor", "FinancialAuditRecorder"]
