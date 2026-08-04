"""The one place that answers "what are this conversation's deadlines?".

See ``docs/architecture/sla-engine.md``.

There were two answers before this existed. The SLA Builder wrote an
``SlaPolicy``, an administrator attached it to a queue, and the clock engine
read targets from the *service directory* alone — so a company with no
services measured nothing, and said so nowhere. The screen that let you
configure an SLA and the engine that enforced one were not looking at the same
fact.

Resolution order is **service, then queue, then platform default**, which is
the order already adopted for the AI confidence threshold: the narrower
configuration wins and the broader one is a fallback, never an override.

The decision itself lives in ``domain.sla.resolve_sla_targets``. This class
only does the reading — which is the point of the split: the rule is testable
without a database, and there is exactly one of it.
"""

from uuid import UUID

from blinkengage.domain.service_context import SlaTargets
from blinkengage.domain.sla import ResolvedSlaTargets, resolve_sla_targets
from blinkengage.infrastructure.repositories.queue_repository import QueueRepository
from blinkengage.infrastructure.repositories.sla_policy_repository import SlaPolicyRepository


class SlaTargetResolver:
    def __init__(self, *, queues: QueueRepository, policies: SlaPolicyRepository) -> None:
        self._queues = queues
        self._policies = policies

    async def for_conversation(
        self, *, company_id: UUID, queue_id: UUID | None, service: SlaTargets | None
    ) -> ResolvedSlaTargets:
        """Targets, and which tier supplied them."""
        return resolve_sla_targets(
            service=service,
            queue=await self._queue_targets(company_id=company_id, queue_id=queue_id),
        )

    async def _queue_targets(self, *, company_id: UUID, queue_id: UUID | None) -> SlaTargets | None:
        """What a queue promises, whichever way its administrator said it.

        Two shapes mean the same thing here. A queue may carry an attached
        ``SlaPolicy`` — the SLA Builder's output, and what a company
        configuring an SLA today produces — or the flat pair of minute
        targets that predate the builder. Both are a queue-level promise, so
        both belong to this tier; the policy wins where a queue has one,
        because attaching it is the later and more deliberate act.

        Only two of the four clocks can come from here: neither shape has
        ever expressed a queue-wait or next-response target. They stay
        unmeasured rather than being invented, and a company that wants them
        defines a service.
        """
        if queue_id is None:
            return None
        queue = await self._queues.get_by_id(company_id=company_id, queue_id=queue_id)
        if queue is None:
            return None

        if queue.sla_policy_id is not None:
            policy = await self._policies.get_by_id(
                company_id=company_id, policy_id=queue.sla_policy_id
            )
            # A policy that was deleted out from under the queue leaves the
            # FK nulled (`ondelete="SET NULL"`), so this is belt and braces
            # — but falling through to the legacy targets is the right
            # answer if it ever is not.
            if policy is not None and policy.is_active:
                return SlaTargets(
                    first_response_minutes=policy.first_response_target_minutes,
                    resolution_minutes=policy.resolution_target_minutes,
                )

        return SlaTargets(
            first_response_minutes=queue.first_response_target_minutes,
            resolution_minutes=queue.resolution_target_minutes,
        )


__all__ = ["SlaTargetResolver"]
