"""The orchestration seam, named before it is built.

``ToolExecutor`` has been production-ready since M2B and its only caller is the
endpoint a *human* uses to confirm or reject an action it parked. There is no
planner: nothing assembles context, chooses tools, or decides whether the
platform is entitled to answer. That gap is what the Brain is for, and this
protocol is where the implementation will attach.

Phase 1 defines the boundary and no implementation. That is deliberate rather
than unfinished: the guard tests below it pin the rules an implementation must
satisfy, and pinning them before there is a caller is the cheap moment. A
protocol with tested rules and no implementation is a contract; an
implementation with untested rules is a liability.

**The Brain advises; it does not send.** ``AutopilotService`` remains the only
autonomous path to a customer, with its existing eligibility, threshold and
handoff logic. An orchestrator returning :class:`BrainAdvice` cannot bypass
that — it has nothing to send with, which is the point.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from blinkengage.domain.brain.context import BrainAdvice, BrainRequest


@runtime_checkable
class BrainOrchestrator(Protocol):
    """One turn in, one piece of advice out.

    Implementations own the ordering the architecture document describes —
    intent, tenant-scoped retrieval, memory, policy, conflict detection,
    response strategy — but the signature is what matters here: a request that
    cannot be made without a company, and a result that cannot be sent.
    """

    async def advise(self, request: BrainRequest) -> BrainAdvice:
        """Assemble grounding and a response strategy for one message.

        Must not raise for an unanswerable question. "The platform does not
        know" is a normal outcome carried in the strategy, not an exception —
        an orchestrator that raised on absence would push callers into
        ``except`` blocks, and an ``except`` block is where a fallback to
        ungrounded generation gets written.
        """
        ...


__all__ = ["BrainOrchestrator"]
