"""``WorkflowAction`` — the plugin contract for one step in a workflow's
action list, plus the execution context every action runs with. See
``docs/architecture/workflow-engine.md``.

Lives in ``application/``, not ``domain/``: unlike ``ChannelProvider``
(a pure domain contract so a third-party channel plugin author never
needs SQLAlchemy/FastAPI in scope), workflow actions are internal,
first-party orchestration — they legitimately need
``ConversationService``/repositories, the same way
``AssignmentEngine``/``RoutingEngine`` do. Forcing this into ``domain/``
would mean either leaking infrastructure types into the domain layer or
re-deriving business logic (status-transition validation, provider
dispatch) that ``ConversationService`` already implements correctly.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.application.services.conversation_service import ConversationService
from blinkengage.domain.events import DomainEventPublisher


@dataclass(slots=True)
class WorkflowExecutionContext:
    session: AsyncSession
    company_id: UUID
    event: dict[str, Any]
    events: DomainEventPublisher
    conversation_service: ConversationService


class WorkflowAction(ABC):
    @abstractmethod
    async def execute(
        self, *, params: dict[str, Any], context: WorkflowExecutionContext
    ) -> dict[str, Any]:
        """Returns a small JSON-serializable result dict — recorded
        verbatim on the triggering ``WorkflowRun.actions_executed`` audit
        trail, so keep it to strings/numbers/bools, never ORM instances."""
