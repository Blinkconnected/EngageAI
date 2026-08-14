"""The state a piece of ingestion is in, and the moves it may legally make.

Before this, ingestion was durable only in the sense that its *inputs* were:
the source message and the document survived a crash, but "we were halfway
through reading this and the worker died" was not a fact anybody could query.
A job is that fact.

Two design choices carry the weight:

**The legal moves are a table, not a chain of ``if``s.** An illegal transition
is a programming error and is refused loudly, because the states this machine
guards are the difference between "not yet read" and "read and rejected" — and
a silent jump between them is how a failed extraction becomes an authoritative
price.

**Nothing reaches ``APPROVED`` in this phase.** ``PROPOSED``/``APPROVED`` are
declared because a state machine missing its exits invites somebody to add them
ad hoc later; 4E and publication are not authorized, so the transitions into
them exist and no caller makes them. That is deliberate, and the guard test
asserts it.
"""

from __future__ import annotations

from enum import StrEnum


class JobState(StrEnum):
    """Where one unit of ingestion work has got to."""

    #: Persisted, not yet worked.
    RECEIVED = "RECEIVED"
    #: A worker has claimed it. Crash here leaves this state behind, which is
    #: how a stuck job is distinguished from an untouched one.
    EXTRACTING = "EXTRACTING"
    #: Text obtained. The end of the road in this phase.
    EXTRACTED = "EXTRACTED"
    #: Facts proposed from the text. 4E; nothing reaches this yet.
    PROPOSED = "PROPOSED"
    #: A human published what was proposed. Publication is not in this phase.
    APPROVED = "APPROVED"
    #: A human declined it.
    REJECTED = "REJECTED"
    #: Transient: a provider timed out, storage was unavailable, the database
    #: deadlocked. Eligible for another attempt until the cap.
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    #: Permanent: an encrypted PDF is encrypted on the second attempt too.
    FAILED_TERMINAL = "FAILED_TERMINAL"


#: Attempts before a retryable failure is treated as permanent.
#:
#: Bounded because an unbounded retry against a genuinely broken document is a
#: worker spinning forever on a file that will never parse, and the queue it
#: occupies belongs to every other company too.
MAX_ATTEMPTS = 5

#: States from which nothing further happens without a human.
TERMINAL_STATES: frozenset[JobState] = frozenset(
    {
        JobState.EXTRACTED,
        JobState.APPROVED,
        JobState.REJECTED,
        JobState.FAILED_TERMINAL,
    }
)

#: States a job may be picked up from by a sweep.
RESUMABLE_STATES: frozenset[JobState] = frozenset({JobState.RECEIVED, JobState.FAILED_RETRYABLE})

#: The legal moves. Anything absent is a defect, not a case to handle.
#:
#: ``EXTRACTING -> RECEIVED`` is deliberately absent: a job whose worker died
#: is *not* untouched, and pretending otherwise loses the one signal that says
#: somebody should look at it. Recovery goes through FAILED_RETRYABLE.
LEGAL_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.RECEIVED: frozenset(
        {JobState.EXTRACTING, JobState.FAILED_RETRYABLE, JobState.FAILED_TERMINAL}
    ),
    JobState.EXTRACTING: frozenset(
        {JobState.EXTRACTED, JobState.FAILED_RETRYABLE, JobState.FAILED_TERMINAL}
    ),
    # FAILED_RETRYABLE is reachable from here because fact extraction runs
    # *after* the document was read: a provider timeout at that point is
    # transient and must be retryable, even though the text is already in
    # hand. Recovery re-enters through EXTRACTING, which re-reads a document
    # that is already extracted — cheap, and the alternative was a second
    # pair of states for the same shape of work.
    JobState.EXTRACTED: frozenset(
        {JobState.PROPOSED, JobState.FAILED_RETRYABLE, JobState.FAILED_TERMINAL}
    ),
    JobState.PROPOSED: frozenset({JobState.APPROVED, JobState.REJECTED}),
    # A retryable failure goes back to work, or gives up. It never jumps
    # straight to EXTRACTED: the work has to actually happen again.
    JobState.FAILED_RETRYABLE: frozenset({JobState.EXTRACTING, JobState.FAILED_TERMINAL}),
    JobState.APPROVED: frozenset(),
    JobState.REJECTED: frozenset(),
    JobState.FAILED_TERMINAL: frozenset(),
}


class InvalidJobTransition(Exception):
    """A move the machine does not allow.

    Raised rather than ignored. The states here separate "not yet read" from
    "read and rejected", and a silent jump between them is how a failed
    extraction becomes an authoritative price.
    """

    def __init__(self, current: JobState, requested: JobState) -> None:
        super().__init__(f"{current.value} -> {requested.value} is not a legal transition")
        self.current = current
        self.requested = requested


def can_transition(current: JobState, requested: JobState) -> bool:
    return requested in LEGAL_TRANSITIONS.get(current, frozenset())


def assert_transition(current: JobState, requested: JobState) -> None:
    if not can_transition(current, requested):
        raise InvalidJobTransition(current, requested)


def failure_state(*, retryable: bool, attempts: int, max_attempts: int = MAX_ATTEMPTS) -> JobState:
    """Where a failure lands.

    A retryable failure that has exhausted its attempts becomes terminal — the
    alternative is a job that is retryable forever and therefore never looked
    at by a person.
    """
    if not retryable:
        return JobState.FAILED_TERMINAL
    return JobState.FAILED_RETRYABLE if attempts < max_attempts else JobState.FAILED_TERMINAL


def grants_authority(state: JobState) -> bool:
    """Whether reaching this state may make knowledge authoritative.

    Always false, in every state, in this phase. Publication is a human act
    behind ``publication_gate()``; a job state is a record of work, and work
    completing is not approval. Stated as a function so the guard test has
    something to bind to and so a future phase has to change it deliberately.
    """
    return False


__all__ = [
    "LEGAL_TRANSITIONS",
    "MAX_ATTEMPTS",
    "RESUMABLE_STATES",
    "TERMINAL_STATES",
    "InvalidJobTransition",
    "JobState",
    "assert_transition",
    "can_transition",
    "failure_state",
    "grants_authority",
]
