"""The one place that answers "what is configured for this conversation?".

See ``docs/architecture/service-centric-migration.md``.

There were nine fallbacks before this, and they did not agree. SLA targets
resolved service → queue → platform through one resolver; the AI confidence
threshold resolved service → company through another; the AI pickup delay had a
hard-coded ``0`` in the ingest consumer; whether AI could engage was a Policy
Engine evaluation on one path and five inline conditions on the other. Three of
those were real chains and three were branches that changed behaviour silently.

This class reads the tiers. **The rules live in ``domain/``** — SLA targets in
``domain/sla.py``, AI policy in ``domain/ai_policy.py`` — which is the point of
the split: each rule is testable without a database, and there is exactly one
of it.

Every answer carries the tier that produced it, so an engine acting on one can
record *why* alongside *what*. That is what makes "why is this conversation due
in three minutes" answerable a month later, when the service has been edited
twice since.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from blinkengage.domain.ai_policy import (
    CompanyAiSettings,
    ResolvedAiPolicy,
    resolve_ai_policy,
)
from blinkengage.domain.company_settings import (
    autopilot_confidence_threshold,
    is_ai_enabled,
    is_autopilot_enabled,
)
from blinkengage.domain.service_context import ServiceContext, SlaTargets
from blinkengage.domain.sla import ResolvedSlaTargets, resolve_sla_targets
from blinkengage.infrastructure.repositories.queue_repository import QueueRepository
from blinkengage.infrastructure.repositories.sla_policy_repository import SlaPolicyRepository

if TYPE_CHECKING:  # pragma: no cover - typing only
    from blinkengage.infrastructure.database.models.company import Company
    from blinkengage.infrastructure.database.models.queue import Queue
    from blinkengage.infrastructure.database.models.sla import SlaPolicy


@dataclass(frozen=True, slots=True)
class ConversationConfiguration:
    """Everything resolved for one conversation, in one read.

    Assembled together rather than fetched fact by fact because the tiers are
    the same three rows every time: asking four questions separately would be
    four round trips to answer one question about one conversation.
    """

    sla: ResolvedSlaTargets
    ai: ResolvedAiPolicy

    # Business-hours awareness is deliberately *not* here yet. The tier exists
    # (``SlaPolicy.business_hours_aware``) and the eligibility model needs it,
    # but nothing reads it today — and a resolved field with no reader cannot
    # be verified, which is the exact failure mode this whole chain was built
    # to end. It arrives with its consumer.


class ConfigurationResolver:
    def __init__(self, *, queues: QueueRepository, policies: SlaPolicyRepository) -> None:
        self._queues = queues
        self._policies = policies

    async def for_conversation(
        self,
        *,
        company_id: UUID,
        queue_id: UUID | None,
        service: ServiceContext | None,
        company: Company | None,
    ) -> ConversationConfiguration:
        """Resolve every configured fact for one conversation."""
        queue = await self._queue(company_id=company_id, queue_id=queue_id)
        settings = company.settings if company is not None else {}
        policy = queue.sla_policy_id if queue is not None else None
        sla_policy = (
            await self._policies.get_by_id(company_id=company_id, policy_id=policy)
            if policy is not None
            else None
        )

        return ConversationConfiguration(
            sla=resolve_sla_targets(
                service=service.sla if service is not None else None,
                queue=_queue_targets(queue, sla_policy),
            ),
            ai=resolve_ai_policy(
                service=service.ai if service is not None else None,
                company=CompanyAiSettings(
                    enabled=is_ai_enabled(settings),
                    autopilot_enabled=is_autopilot_enabled(settings),
                    # Read as the company's *stated* value rather than the
                    # effective one: this is a tier, and letting it arrive
                    # pre-merged with the service would resolve the chain
                    # twice and lose which tier answered.
                    confidence_threshold=Decimal(str(autopilot_confidence_threshold(settings))),
                ),
            ),
        )

    async def _queue(self, *, company_id: UUID, queue_id: UUID | None) -> Queue | None:
        if queue_id is None:
            return None
        return await self._queues.get_by_id(company_id=company_id, queue_id=queue_id)


def _queue_targets(queue: Queue | None, policy: SlaPolicy | None) -> SlaTargets | None:
    """What a queue promises, whichever way its administrator said it.

    Two shapes mean the same thing here. A queue may carry an attached
    ``SlaPolicy`` — the SLA Builder's output, and what a company configuring an
    SLA today produces — or the flat pair of minute targets that predate the
    builder. Both are a queue-level promise, so both belong to this tier; the
    policy wins where a queue has one, because attaching it is the later and
    more deliberate act.

    Only two of the four clocks can come from here: neither shape has ever
    expressed a queue-wait or next-response target. They stay unmeasured rather
    than invented, and a company that wants them defines a service.
    """
    if queue is None:
        return None
    if policy is not None and policy.is_active:
        # A policy deleted out from under the queue leaves the FK nulled
        # (``ondelete="SET NULL"``), so reaching here with an inactive one is
        # belt and braces — but falling through to the legacy targets is the
        # right answer if it ever is not.
        return SlaTargets(
            first_response_minutes=policy.first_response_target_minutes,
            resolution_minutes=policy.resolution_target_minutes,
        )
    return SlaTargets(
        first_response_minutes=queue.first_response_target_minutes,
        resolution_minutes=queue.resolution_target_minutes,
    )


__all__ = ["ConfigurationResolver", "ConversationConfiguration"]
