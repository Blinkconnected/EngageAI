"""How a conversation ended, defined once.

Pure — no I/O, no clock beyond what a caller passes.

**Why this module exists.** "Was this resolved?", "was it first-contact?",
"did it escalate?" were about to acquire two implementations: Reporting
already derives them into daily statistics, and the Learning Platform's
observation envelope was specified to carry its own. Two definitions of
first-contact resolution means Learning's beliefs would be built on a
number Reporting contradicts, and nothing would report the disagreement.

That is not a hypothetical failure mode in this codebase. The ownership
audit records **A3**: SLA targets had two owners, the UI wrote one and the
engine read the other, and the consequence was zero SLA clocks across the
entire installation with nothing reporting a problem. One resolver, the
way ``effective_autopilot_confidence_threshold`` is one resolver.

**Who resolved it is part of the outcome.** A conversation closed by a
workflow rule reads as ``resolved`` on the status column, and anything
learning from outcomes would conclude that whatever preceded the
auto-close worked. That is a feedback loop distinct from the AI one — a
workflow is not AI, so excluding AI-generated content does not touch it —
and the only way to see it is for the outcome to say *who* ended the
conversation. ``outcome_quality`` then discounts what a machine decided.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

#: How long after a conversation ends its outcome may still change.
#:
#: CSAT arrives minutes to days late, and a reopen invalidates resolution
#: entirely. An observation consumed before this elapses is consumed with
#: an outcome that is not final — which enters confidence as a neutral
#: ``outcome_quality`` for conversations that were in fact rated badly.
#:
#: Deliberately far shorter than the 14-day CSAT token life: waiting for
#: the last possible response would make every observation two weeks stale
#: and learning useless. This is the window in which the overwhelming
#: majority of responses arrive.
DEFAULT_SETTLE_HOURS = 72

#: A reopen after this long is a new problem, not a failed resolution.
DEFAULT_REOPEN_WINDOW_HOURS = 168


class ResolvedBy(StrEnum):
    """Who ended the conversation.

    The distinction that stops a machine's decision being read as a
    success. ``UNKNOWN`` is a real answer for conversations that ended
    before the platform recorded ownership transitions, and it is treated
    as un-attributable rather than guessed at.
    """

    HUMAN = "human"
    AI = "ai"
    WORKFLOW = "workflow"
    #: Closed by a timeout or an inactivity sweep — nobody decided
    #: anything, which is the weakest possible evidence of success.
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


#: Which resolvers count as evidence that something *worked*.
#:
#: A human closing a conversation is a person judging it finished. A
#: workflow or a timeout closing it is a rule firing, and reading that as
#: success is how a platform learns that whatever precedes an auto-close
#: is effective. AI sits in the middle and is excluded for the separate
#: reason that it is the platform's own output.
ATTRIBUTABLE_RESOLVERS: frozenset[ResolvedBy] = frozenset({ResolvedBy.HUMAN})


@dataclass(frozen=True)
class OutcomeInputs:
    """Everything the derivation may look at.

    A record rather than a parameter list, so a caller that forgets an
    input gets a type error and every call site visibly supplies the same
    shape — which is the point of there being one definition.
    """

    status: str
    ended_at: datetime | None
    started_at: datetime
    now: datetime
    resolved_by: ResolvedBy = ResolvedBy.UNKNOWN
    inbound_message_count: int = 0
    outbound_message_count: int = 0
    reopened_at: datetime | None = None
    escalated: bool = False
    transferred_count: int = 0
    csat_score: int | None = None
    csat_scale_max: int = 5
    settle_hours: int = DEFAULT_SETTLE_HOURS
    reopen_window_hours: int = DEFAULT_REOPEN_WINDOW_HOURS

    def __post_init__(self) -> None:
        """Normalise every timestamp to UTC-aware, once, here.

        Callers hand these over straight from ORM rows, and the two
        supported backends disagree about what comes back: PostgreSQL
        ``timestamptz`` yields aware datetimes, SQLite yields naive ones.
        Subtracting one from the other raises, so without this the
        derivation works in production and fails in the test suite — or,
        worse, the reverse.

        Normalising at the boundary rather than at each of the four
        arithmetic sites is deliberate: this is the *single* outcome
        resolver, and a rule enforced once at its entrance cannot be
        forgotten by a branch added later. A naive value is read as UTC,
        which is what both backends store.
        """
        for field_name in ("ended_at", "started_at", "now", "reopened_at"):
            value = getattr(self, field_name)
            if isinstance(value, datetime) and value.tzinfo is None:
                object.__setattr__(self, field_name, value.replace(tzinfo=UTC))


@dataclass(frozen=True)
class Outcome:
    """What happened, and how much it is worth believing."""

    resolved: bool
    resolved_by: ResolvedBy
    reopened: bool
    escalated: bool
    first_contact_resolution: bool
    handling_seconds: int | None
    csat_score: int | None
    #: 0–1, or ``None`` where nothing measured it. **Never zero for
    #: "unmeasured"** — most conversations have no CSAT, and treating
    #: unmeasured as bad would mean only the surveyed minority could ever
    #: be believed.
    quality: float | None
    #: Whether the outcome may still change. An unsettled outcome is not
    #: wrong, it is *provisional*, and anything that learns from it must
    #: wait.
    settled: bool

    @property
    def attributable(self) -> bool:
        """Whether this outcome is evidence that something worked.

        False for machine-ended conversations, which is what keeps a
        workflow auto-close from teaching the platform that whatever
        preceded it succeeded.
        """
        return self.resolved and self.resolved_by in ATTRIBUTABLE_RESOLVERS


_FINISHED = frozenset({"resolved", "closed"})


def derive(inputs: OutcomeInputs) -> Outcome:
    """The one derivation. Every consumer calls this."""
    resolved = inputs.status in _FINISHED
    reopened = _reopened(inputs)

    handling_seconds = (
        int((inputs.ended_at - inputs.started_at).total_seconds())
        if inputs.ended_at is not None and inputs.ended_at >= inputs.started_at
        else None
    )

    # First contact means one inbound turn and no escalation, transfer or
    # reopen. Counting only messages would call a conversation that was
    # transferred twice and answered once "first contact", which is the
    # reading that makes the metric flattering and useless.
    first_contact = (
        resolved
        and not reopened
        and not inputs.escalated
        and inputs.transferred_count == 0
        and inputs.inbound_message_count <= 1
    )

    return Outcome(
        resolved=resolved,
        resolved_by=inputs.resolved_by,
        reopened=reopened,
        escalated=inputs.escalated,
        first_contact_resolution=first_contact,
        handling_seconds=handling_seconds,
        csat_score=inputs.csat_score,
        quality=_quality(inputs, resolved=resolved, reopened=reopened),
        settled=is_settled(inputs),
    )


def _reopened(inputs: OutcomeInputs) -> bool:
    if inputs.reopened_at is None or inputs.ended_at is None:
        return False
    return inputs.reopened_at - inputs.ended_at <= timedelta(hours=inputs.reopen_window_hours)


def _quality(inputs: OutcomeInputs, *, resolved: bool, reopened: bool) -> float | None:
    """How good the outcome was, in ``[0, 1]``.

    CSAT dominates where it exists, because a customer saying so beats any
    inference. Where it does not, the answer is ``None`` — not a guess
    dressed as a measurement.
    """
    if inputs.csat_score is not None and inputs.csat_scale_max > 1:
        score = (inputs.csat_score - 1) / (inputs.csat_scale_max - 1)
        return max(0.0, min(1.0, score))

    if not resolved:
        return None
    if reopened or inputs.escalated:
        # Structural evidence that it went badly, available without a
        # survey. Not a full zero: a reopened conversation may still have
        # been handled well the second time.
        return 0.25
    # Resolved, not reopened, not escalated, and nobody asked the
    # customer. Genuinely unmeasured.
    return None


def is_settled(inputs: OutcomeInputs) -> bool:
    """Whether the outcome may still change.

    An observation is not *eligible* for learning until this is true. The
    Learning Platform's cluster evaluation runs hourly; without this it
    would consume conversations whose CSAT has not landed and enter a
    neutral quality for conversations that were in fact rated badly.

    A conversation that already has CSAT is settled immediately — the
    thing the window was waiting for has arrived, and waiting further
    would delay learning for no gain.
    """
    if inputs.status not in _FINISHED:
        return False
    if inputs.csat_score is not None:
        return True
    if inputs.ended_at is None:
        return False
    return inputs.now - inputs.ended_at >= timedelta(hours=inputs.settle_hours)


__all__ = [
    "ATTRIBUTABLE_RESOLVERS",
    "DEFAULT_REOPEN_WINDOW_HOURS",
    "DEFAULT_SETTLE_HOURS",
    "Outcome",
    "OutcomeInputs",
    "ResolvedBy",
    "derive",
    "is_settled",
]
