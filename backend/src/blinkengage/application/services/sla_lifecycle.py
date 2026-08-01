"""What happens to the clocks when something happens to the conversation.

See ``docs/architecture/sla-engine.md``.

The rules live here rather than at each call site, because they are the part
somebody will get subtly wrong: which clocks a status change pauses, whether a
reply settles one clock or two, what a close does to the ones still running.
Spread across the ingest consumer and the conversation service they would drift
apart, and the drift would show up as an SLA report nobody trusts.

``SlaEngine`` is the *mechanism* — start, pause, resume, settle. This is the
*policy*: when each of those is right. Keeping them apart is what lets the
mechanism be tested exhaustively without a conversation, and the policy be read
in one page.

Every method is a no-op when the engine is absent, so a caller that has not
been wired yet behaves exactly as it did before rather than failing.
"""

from datetime import datetime
from uuid import UUID

from blinkengage.application.services.sla_engine import SlaEngine
from blinkengage.domain.lifecycle import ConversationStatus
from blinkengage.domain.service_context import SlaTargets
from blinkengage.domain.sla import PauseReason, SlaState, SlaTimer

#: The clocks a conversation starts with when it enters a queue. Not the next
#: response clock: nobody is waiting for a *next* reply before the first one
#: has happened, and starting it here would show every new conversation as
#: overdue on a promise that had not been made yet.
_ON_QUEUE: tuple[SlaTimer, ...] = (
    SlaTimer.QUEUE,
    SlaTimer.FIRST_RESPONSE,
    SlaTimer.RESOLUTION,
)

#: The clocks that pause when the ball is with the customer. The queue clock
#: is absent deliberately — it has already stopped by then, and a conversation
#: still waiting for an owner is not waiting on the customer.
_PAUSABLE: tuple[SlaTimer, ...] = (
    SlaTimer.FIRST_RESPONSE,
    SlaTimer.NEXT_RESPONSE,
    SlaTimer.RESOLUTION,
)


class SlaLifecycle:
    """Drives the clocks from the conversation's own events."""

    def __init__(self, engine: SlaEngine | None) -> None:
        self._engine = engine

    async def queued(
        self,
        *,
        conversation_id: UUID,
        company_id: UUID,
        targets: SlaTargets,
        now: datetime | None = None,
    ) -> None:
        """A conversation entered a queue.

        Three clocks start together. The customer is now waiting for
        somebody to take it, waiting for a first reply, and waiting for the
        whole thing to be over — all true at once, which is why they are
        separate clocks rather than one.
        """
        if self._engine is None:
            return
        for timer in _ON_QUEUE:
            await self._engine.start(
                conversation_id=conversation_id,
                company_id=company_id,
                timer=timer,
                targets=targets,
                now=now,
            )

    async def owner_accepted(self, *, conversation_id: UUID, now: datetime | None = None) -> None:
        """Somebody — a person or AI — took responsibility.

        The queue clock is *achieved* here, on acceptance rather than on
        reply. "How long has this customer been waiting for ownership?" is
        answered the moment somebody owns it; making it wait for a reply
        would fold two questions into one clock and leave the first
        unanswerable.
        """
        if self._engine is None:
            return
        await self._engine.achieve(conversation_id=conversation_id, timer=SlaTimer.QUEUE, now=now)

    async def replied(
        self, *, conversation_id: UUID, was_first: bool, now: datetime | None = None
    ) -> None:
        """A reply went out to the customer.

        Settles the first-response clock when it is the first, and the
        next-response clock always — a reply answers whatever the customer
        was last waiting for.
        """
        if self._engine is None:
            return
        if was_first:
            await self._engine.achieve(
                conversation_id=conversation_id, timer=SlaTimer.FIRST_RESPONSE, now=now
            )
        await self._engine.achieve(
            conversation_id=conversation_id, timer=SlaTimer.NEXT_RESPONSE, now=now
        )

    async def customer_replied(
        self,
        *,
        conversation_id: UUID,
        company_id: UUID,
        targets: SlaTargets,
        now: datetime | None = None,
    ) -> None:
        """The customer sent a message, so the ball is back with us.

        Starts the next-response clock and resumes anything paused for the
        customer. Resuming is not the same as restarting: the time already
        counted stays counted, which is what stops a long conversation
        quietly resetting its own resolution target every time the customer
        writes.
        """
        if self._engine is None:
            return
        await self._engine.start(
            conversation_id=conversation_id,
            company_id=company_id,
            timer=SlaTimer.NEXT_RESPONSE,
            targets=targets,
            now=now,
        )
        for timer in _PAUSABLE:
            await self._engine.resume(conversation_id=conversation_id, timer=timer, now=now)

    async def status_changed(
        self,
        *,
        conversation_id: UUID,
        status: ConversationStatus,
        now: datetime | None = None,
    ) -> None:
        """A status change, translated into what it means for the clocks.

        The one place the two concepts touch — and deliberately a
        translation rather than a coupling: the lifecycle does not know
        about clocks, the clocks do not know about statuses, and this reads
        one into the other in a table somebody can check.
        """
        if self._engine is None:
            return

        if status is ConversationStatus.WAITING_CUSTOMER:
            for timer in _PAUSABLE:
                await self._engine.pause(
                    conversation_id=conversation_id,
                    timer=timer,
                    reason=PauseReason.WAITING_FOR_CUSTOMER,
                    now=now,
                )
            return

        if status is ConversationStatus.WAITING_AGENT:
            # Blocked on somebody inside the business. Still our delay, so
            # the resolution clock keeps running — but the *response*
            # clocks pause, because nobody can reply until the block
            # clears and holding an agent to a reply target they cannot
            # meet is how an SLA stops being believed.
            for timer in (SlaTimer.FIRST_RESPONSE, SlaTimer.NEXT_RESPONSE):
                await self._engine.pause(
                    conversation_id=conversation_id,
                    timer=timer,
                    reason=PauseReason.DEPENDENCY_WAITING,
                    now=now,
                )
            return

        if status is ConversationStatus.RESOLVED:
            await self._engine.achieve(
                conversation_id=conversation_id, timer=SlaTimer.RESOLUTION, now=now
            )
            return

        if status is ConversationStatus.CLOSED:
            # Whatever is still running never got a verdict. Stopped, not
            # achieved — counting an abandoned conversation as a success is
            # how a dashboard lies.
            for timer in SlaTimer:
                await self._engine.settle(
                    conversation_id=conversation_id,
                    timer=timer,
                    state=SlaState.STOPPED,
                    now=now,
                )
            return

        if status in (ConversationStatus.IN_PROGRESS, ConversationStatus.WAITING):
            for timer in _PAUSABLE:
                await self._engine.resume(conversation_id=conversation_id, timer=timer, now=now)


__all__ = ["SlaLifecycle"]
