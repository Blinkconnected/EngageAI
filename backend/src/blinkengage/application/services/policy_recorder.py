"""Policies that write down every answer they give.

See ``docs/architecture/policy-engine.md``.

**A policy must never silently allow or deny anything.** The Policy Engine
itself is pure — no repository, no clock — because that is what makes its
rules exhaustively testable. This is the layer that makes them explainable:
every evaluation that *gates* something writes a routing decision, so no
module can permit or refuse behaviour without leaving a record of why.

Structural, not a convention. ``evaluate`` records; there is no flag to pass
and none to forget. A module handed one of these cannot ask a policy quietly.

---

**The one distinction that has to exist**, and the reason it is drawn here
rather than argued about at each call site: *asking* is not *deciding*.

The Routing Inspector shows what the platform would allow right now — nine
policies, on a screen somebody opens to understand a conversation. If those
evaluations wrote decisions, opening the Inspector would append nine rows
about the act of looking, the log would fill with the observer rather than the
system, and a conversation's history would change every time somebody read it.

So enforcement records and inspection does not, and the two are different
methods with different names. ``evaluate`` gates behaviour and always writes;
``preview`` answers questions and never does. Nothing needs to remember which
is which, because the method that cannot record is also the method whose
answer nothing is allowed to act on.
"""

import uuid

from blinkengage.domain.execution_context import ExecutionContext
from blinkengage.domain.policies import (
    Policy,
    PolicyDecision,
    PolicyEngine,
    as_routing_decision,
)
from blinkengage.infrastructure.repositories.routing_decision_repository import (
    RoutingDecisionRepository,
)


class RecordingPolicyEngine:
    """The Policy Engine as a module receives it: answering, and recording.

    Bound to one conversation, because a policy evaluation is always *about*
    a conversation and a decision row that did not say which would explain
    nothing. Constructed per execution rather than injected once, which is
    also what stops a long-lived instance recording against the wrong one.
    """

    def __init__(
        self,
        engine: PolicyEngine,
        decisions: RoutingDecisionRepository,
        *,
        company_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ) -> None:
        self._engine = engine
        self._decisions = decisions
        self._company_id = company_id
        self._conversation_id = conversation_id

    async def evaluate(self, policy: Policy, execution: ExecutionContext) -> PolicyDecision:
        """Answer one policy, and write down that it was asked.

        Records **allow as well as deny**. A log holding only refusals
        answers "why was this blocked?" and not "why was this permitted?",
        and the second question is the one asked after something reached a
        customer that should not have.
        """
        decision = self._engine.evaluate(policy, execution)
        await self._record(decision)
        return decision

    def preview(self, execution: ExecutionContext) -> dict[Policy, PolicyDecision]:
        """Every policy, answered and **not** recorded.

        For the Routing Inspector: what the platform would allow right now.
        Deliberately synchronous and deliberately without a repository, so a
        caller cannot use it to gate behaviour and quietly skip the record —
        the method that does not write is also the one whose answer nothing
        may act on.
        """
        return self._engine.evaluate_all(execution)

    async def _record(self, decision: PolicyDecision) -> None:
        """Never at the cost of the thing being decided.

        Same tradeoff as ``_record_decision`` in the ingest consumer, for the
        same reason: routing and AI are the product, the explanation is
        evidence *about* the product, and an evaluation that could not be
        written must not stop a customer being answered.
        """
        try:
            await self._decisions.record(
                company_id=self._company_id,
                conversation_id=self._conversation_id,
                decision=as_routing_decision(decision),
            )
        except Exception:  # noqa: BLE001 — see the docstring: never fatal.
            from blinkengage.core.logging import get_logger

            get_logger(__name__).warning(
                "policy_decision_not_recorded",
                policy=decision.policy.value,
                conversation_id=str(self._conversation_id),
                exc_info=True,
            )


__all__ = ["RecordingPolicyEngine"]
