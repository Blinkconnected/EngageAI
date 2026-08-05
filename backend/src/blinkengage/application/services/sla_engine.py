"""Starting, pausing and settling the four clocks.

See ``docs/architecture/sla-engine.md``.

Every method here does two things and always both: it moves the clock, and it
writes the transition into the conversation's decision log. A clock that
changed without a row would be a deadline nobody could explain, which is the
one thing the SLA engine must never produce.

**The service owns the targets.** They are copied onto the clock when it
starts, from the service version the conversation is bound to — not read
through it on every check. A conversation's targets are frozen at its start,
so an administrator halving a target at noon must not move the deadline of
everything already running, and copying is what makes that true without a join
on every sweep.

Nothing here decides *when* to call these. That belongs to the events the
platform already has — a conversation entering a queue, an owner accepting it,
a message going out, a status changing — and keeping the decision at the call
site is what stops this module growing a second opinion about the lifecycle.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.core.logging import get_logger
from blinkengage.domain.service_context import SlaTargets
from blinkengage.domain.sla import (
    RECORDED_AS,
    Clock,
    PauseReason,
    SlaHealth,
    SlaState,
    SlaTargetSource,
    SlaTimer,
    as_routing_decision,
    overall,
)
from blinkengage.infrastructure.database.models.sla_clock import ConversationSlaClock
from blinkengage.infrastructure.repositories.routing_decision_repository import (
    RoutingDecisionRepository,
)

logger = get_logger(__name__)

#: Which service target feeds which clock. A mapping rather than four
#: hand-written lookups, so a clock added later cannot silently start
#: measuring nothing.
_TARGET: dict[SlaTimer, str] = {
    SlaTimer.QUEUE: "queue_minutes",
    SlaTimer.FIRST_RESPONSE: "first_response_minutes",
    SlaTimer.NEXT_RESPONSE: "next_response_minutes",
    SlaTimer.RESOLUTION: "resolution_minutes",
}


@dataclass(frozen=True, slots=True)
class ConversationSla:
    """Every clock on one conversation, and the one thing to act on.

    ``health`` is the primary reading. Four timers side by side is a report;
    one indicator is a decision. The clocks stay available underneath for
    anybody who needs them.
    """

    clocks: list[Clock]
    health: SlaHealth

    def clock(self, timer: SlaTimer) -> Clock | None:
        return next((c for c in self.clocks if c.timer is timer), None)


class SlaEngine:
    def __init__(self, session: AsyncSession, decisions: RoutingDecisionRepository) -> None:
        self._session = session
        self._decisions = decisions

    async def start(
        self,
        *,
        conversation_id: uuid.UUID,
        company_id: uuid.UUID,
        timer: SlaTimer,
        targets: SlaTargets,
        source: SlaTargetSource | None = None,
        now: datetime | None = None,
    ) -> Clock | None:
        """Starts a clock, if the service measures it.

        Returns ``None`` when it does not. A service with no first-response
        target is a real configuration — a back-office queue that answers
        when it answers — and inventing a deadline for it would put a red
        row in front of an agent for a promise nobody made.

        Restarting a clock that is already running is a no-op. The next
        response clock is restarted on every inbound message, and a
        conversation where the customer sends three messages in a row must
        not have its clock reset by the second and third.
        """
        moment = now or datetime.now(UTC)
        target = getattr(targets, _TARGET[timer])
        row = await self._row(conversation_id, timer)

        if target is None:
            return None
        if row is not None and row.state is SlaState.RUNNING:
            return _to_clock(row)

        if row is None:
            row = ConversationSlaClock(
                conversation_id=conversation_id,
                company_id=company_id,
                timer=timer,
                # Set explicitly rather than left to the column default: a
                # column default does not apply until flush, and the
                # deadline below is computed from it before then.
                elapsed=timedelta(),
            )
            self._session.add(row)

        row.target_minutes = target
        # Recorded beside the target it explains. Optional so the many
        # callers that restart a clock (next-response, chiefly) do not have
        # to re-resolve a source that has not changed.
        if source is not None:
            row.target_source = source
        row.state = SlaState.RUNNING
        row.running_since = moment
        row.started_at = row.started_at or moment
        row.pause_reason = None
        row.pause_note = None
        row.settled_at = None
        row.due_at = moment + timedelta(minutes=target) - (row.elapsed or timedelta())
        await self._session.flush()

        return await self._record(row, SlaState.RUNNING, now=moment)

    async def pause(
        self,
        *,
        conversation_id: uuid.UUID,
        timer: SlaTimer,
        reason: PauseReason,
        note: str | None = None,
        now: datetime | None = None,
    ) -> Clock | None:
        """Stops a clock counting, and says why.

        The reason is required, not optional. A paused clock with no reason
        is a deadline that moved for no stated cause, and an agent looking
        at one has no way to know whether to act.
        """
        moment = now or datetime.now(UTC)
        row = await self._row(conversation_id, timer)
        if row is None or row.state is not SlaState.RUNNING:
            # Pausing what is not running is a no-op rather than an error:
            # a customer replying twice in a row would otherwise raise on
            # the second, on the one path where an exception costs a
            # message.
            return None

        if row.running_since is not None:
            row.elapsed = (row.elapsed or timedelta()) + (moment - row.running_since)
        row.state = SlaState.PAUSED
        row.running_since = None
        row.pause_reason = reason
        row.pause_note = note
        # Cleared, which is what keeps a paused clock out of the sweep
        # entirely rather than relying on the sweep to filter it out.
        row.due_at = None
        await self._session.flush()

        return await self._record(row, SlaState.PAUSED, now=moment)

    async def resume(
        self,
        *,
        conversation_id: uuid.UUID,
        timer: SlaTimer,
        now: datetime | None = None,
    ) -> Clock | None:
        """Starts a paused clock counting again, from where it stopped."""
        moment = now or datetime.now(UTC)
        row = await self._row(conversation_id, timer)
        if row is None or row.state is not SlaState.PAUSED or row.target_minutes is None:
            return None

        row.state = SlaState.RUNNING
        row.running_since = moment
        row.pause_reason = None
        row.pause_note = None
        row.due_at = moment + timedelta(minutes=row.target_minutes) - (row.elapsed or timedelta())
        await self._session.flush()

        return await self._record(row, SlaState.RUNNING, now=moment)

    async def settle(
        self,
        *,
        conversation_id: uuid.UUID,
        timer: SlaTimer,
        state: SlaState,
        now: datetime | None = None,
    ) -> Clock | None:
        """Ends a clock — met, missed, or stopped without a verdict.

        Terminal. A breach in particular never un-breaches: it is a fact
        about what happened, and a clock that could reverse would let a late
        reply erase the lateness.
        """
        moment = now or datetime.now(UTC)
        row = await self._row(conversation_id, timer)
        if row is None or row.state in (SlaState.ACHIEVED, SlaState.BREACHED):
            return None

        if row.running_since is not None:
            row.elapsed = (row.elapsed or timedelta()) + (moment - row.running_since)
        row.state = state
        row.running_since = None
        row.settled_at = moment
        row.due_at = None
        await self._session.flush()

        return await self._record(row, state, now=moment)

    async def achieve(self, **kw: object) -> Clock | None:
        """The clock was met. Named for the outcome rather than the state,
        because that is how the call site reads."""
        return await self.settle(state=SlaState.ACHIEVED, **kw)  # type: ignore[arg-type]

    async def stop(self, **kw: object) -> Clock | None:
        """The conversation ended before this clock could be met or missed.

        Not ``achieve``: counting an abandoned conversation as a success is
        how a dashboard lies.
        """
        return await self.settle(state=SlaState.STOPPED, **kw)  # type: ignore[arg-type]

    async def read(
        self, conversation_id: uuid.UUID, *, now: datetime | None = None
    ) -> ConversationSla:
        """Every clock on this conversation, and the worst of them."""
        moment = now or datetime.now(UTC)
        result = await self._session.execute(
            select(ConversationSlaClock).where(
                ConversationSlaClock.conversation_id == conversation_id
            )
        )
        clocks = [_to_clock(row) for row in result.scalars().all()]
        return ConversationSla(clocks=clocks, health=overall(clocks, now=moment))

    async def pause_notes(self, conversation_id: uuid.UUID) -> dict[SlaTimer, str | None]:
        """The free-text note beside each pause, keyed by clock.

        Read separately from the clocks because the note is *additive* — a
        dependency pause can name what it is waiting on, and folding it
        into the structured reason would be exactly the substitution the
        vocabulary exists to prevent.
        """
        result = await self._session.execute(
            select(ConversationSlaClock).where(
                ConversationSlaClock.conversation_id == conversation_id
            )
        )
        return {row.timer: row.pause_note for row in result.scalars().all()}

    async def _row(
        self, conversation_id: uuid.UUID, timer: SlaTimer
    ) -> ConversationSlaClock | None:
        result = await self._session.execute(
            select(ConversationSlaClock).where(
                ConversationSlaClock.conversation_id == conversation_id,
                ConversationSlaClock.timer == timer,
            )
        )
        return result.scalar_one_or_none()

    async def _record(self, row: ConversationSlaClock, state: SlaState, *, now: datetime) -> Clock:
        """Writes the transition, and never costs the conversation.

        Same tradeoff as every other recorder here: the clock moving is the
        product, the row explaining it is evidence, and evidence that would
        not write must not stop a customer being answered.

        **Inside a SAVEPOINT**, for the reason spelled out in the ingest
        consumer's ``_record_decision``: catching the exception is not enough.
        On PostgreSQL a failed statement poisons its whole transaction, so a
        swallowed failure here would take down every later statement — the
        routing, the assignment, the message itself — and the conversation
        would be lost to an audit row. The clock's own pending writes are
        flushed first so the rollback undoes only this insert.
        """
        clock = _to_clock(row)
        kind, reason = RECORDED_AS[state]
        await self._session.flush()
        try:
            async with self._session.begin_nested():
                await self._decisions.record(
                    company_id=row.company_id,
                    conversation_id=row.conversation_id,
                    decision=as_routing_decision(clock, kind=kind, reason=reason, now=now),
                )
        except Exception:  # noqa: BLE001 — see the docstring: never fatal.
            logger.warning(
                "sla_transition_not_recorded",
                conversation_id=str(row.conversation_id),
                timer=row.timer.value,
                exc_info=True,
            )
        return clock


def _to_clock(row: ConversationSlaClock) -> Clock:
    return Clock(
        timer=row.timer,
        state=row.state,
        target_minutes=row.target_minutes,
        target_source=row.target_source,
        elapsed=row.elapsed or timedelta(),
        running_since=row.running_since,
        pause_reason=row.pause_reason,
        settled_at=row.settled_at,
    )


__all__ = ["ConversationSla", "SlaEngine"]
