"""How alive a memory row is — the second axis, and the separation of
forgetting from erasure.

Pure. Every input is passed in; nothing here reads a clock or a row.

**Two axes, not one chain.** The obvious design is a single progression:
observed → candidate → confirmed → trusted → stale → archived → forgotten.
It reads well and it breaks on a case that happens constantly.

A fact reaches ``TRUSTED`` over six months — two hundred supporting
conversations, fourteen agents. The topic goes quiet for a quarter and it
decays to stale. Then it is observed again. On a single chain, where does
it go? Back to candidate discards two hundred conversations of evidence,
so the fact is *less* believed on strictly *more* evidence, which is
incoherent. Jumping straight back to trusted makes "stale" a label that
meant nothing. There is no right answer because the question is malformed:
how much we believe a fact and how alive its row is are different
questions.

So belief lives on ``ConfidenceState`` and liveness lives here. The case
above resolves cleanly — ``DORMANT`` → ``ACTIVE``, confidence untouched,
because the evidence never went anywhere.

**Forgetting is not erasure**, and this module only does the first:

| | Forgetting | Erasure |
|---|---|---|
| Cause | Decay, retention | A legal request |
| Trigger | Scheduled | On demand, must complete |
| Evidence | Pruned on archive | Deleted |
| Reversible | Until purge | Never, by design |
| Answer to an auditor | "It decayed" | "It is gone" |

"It was forgotten" is not an answer to "prove this customer's data is
deleted", so erasure is a separate operation with its own audit record and
lives in ``MemoryErasureService``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from blinkengage.domain.memory import HumanState, LifecycleState

#: How long without a new observation before a fact goes quiet.
DEFAULT_DORMANT_AFTER_DAYS = 180
#: How long dormant before it leaves the working set entirely.
DEFAULT_ARCHIVE_AFTER_DAYS = 545
#: How long archived before the row itself goes. Long, because an archived
#: row is the only remaining evidence that the platform once believed
#: something — which is exactly what an audit asks about.
DEFAULT_PURGE_AFTER_DAYS = 1095


@dataclass(frozen=True)
class RetentionPolicy:
    """Per-company retention, with platform defaults.

    Held as a value object rather than read from settings inline so the
    transitions below stay pure and a company's override is visible at the
    call site instead of buried in a lookup.
    """

    dormant_after_days: int = DEFAULT_DORMANT_AFTER_DAYS
    archive_after_days: int = DEFAULT_ARCHIVE_AFTER_DAYS
    purge_after_days: int = DEFAULT_PURGE_AFTER_DAYS

    def __post_init__(self) -> None:
        if not (0 < self.dormant_after_days < self.archive_after_days < self.purge_after_days):
            raise ValueError(
                "retention must increase strictly: dormant < archive < purge "
                f"(got {self.dormant_after_days}, {self.archive_after_days}, "
                f"{self.purge_after_days})"
            )


@dataclass(frozen=True)
class LifecycleInputs:
    current: LifecycleState
    last_observed_at: datetime
    now: datetime
    human_state: HumanState
    policy: RetentionPolicy
    #: A fact whose evidence has been erased cannot be re-derived and must
    #: not linger in the working set pretending to be supported.
    has_evidence: bool = True
    #: Explicit per-row override — a promise past its due date, an imported
    #: fact with a contractual expiry.
    expires_at: datetime | None = None


def next_lifecycle_state(inputs: LifecycleInputs) -> LifecycleState:
    """Where the row sits on the liveness axis.

    Ordering of the checks is the design:

    1. **A human's suppression outranks the schedule.** Somebody muted this
       deliberately; decaying it to archived would remove it from the
       working set for a reason that has nothing to do with why it was
       muted, and reviving it on re-observation would un-mute it behind
       their back.
    2. **An explicit expiry outranks the default schedule**, because it was
       set by somebody who knew something the schedule does not.
    3. **Losing all evidence archives immediately.** Not purge — the row is
       the record that the platform once believed this, and an erasure that
       silently deleted aggregate facts would remove more than it was asked
       to.
    4. Otherwise, age decides.
    """
    if inputs.human_state is HumanState.SUPPRESSED:
        # Suppressed rows stay exactly where they are. They must not be
        # purged either: a suppressed fact that vanished would simply be
        # re-learned next week, which is the opposite of what suppressing
        # it meant.
        return inputs.current

    age_days = max(0.0, (inputs.now - inputs.last_observed_at).total_seconds() / 86400.0)

    if not inputs.has_evidence:
        return LifecycleState.ARCHIVED

    if inputs.expires_at is not None and inputs.now >= inputs.expires_at:
        return LifecycleState.ARCHIVED

    if age_days >= inputs.policy.purge_after_days:
        return LifecycleState.PURGED
    if age_days >= inputs.policy.archive_after_days:
        return LifecycleState.ARCHIVED
    if age_days >= inputs.policy.dormant_after_days:
        return LifecycleState.DORMANT
    return LifecycleState.ACTIVE


def revive_on_observation(current: LifecycleState) -> LifecycleState:
    """New evidence arrived. What does that do to liveness?

    ``DORMANT`` revives — that is the whole reason the axis is separate,
    and confidence is deliberately left alone so the fact returns with the
    standing it earned.

    ``ARCHIVED`` does **not** revive automatically. Its evidence has been
    pruned, so a revived row would carry counters it can no longer justify;
    bringing it back is a deliberate act, not a side effect of one new
    observation.
    """
    if current is LifecycleState.DORMANT:
        return LifecycleState.ACTIVE
    return current


def is_retrievable(*, lifecycle: LifecycleState, human_state: HumanState) -> bool:
    """Whether a consumer may be shown this fact.

    One function, so every consumer — the AI Engine, the Customer Timeline,
    Reporting, Analytics — agrees. Two readers disagreeing about whether a
    suppressed fact is visible is exactly the fragmentation the Policy
    Engine exists to prevent, applied to memory.
    """
    if human_state is HumanState.SUPPRESSED:
        return False
    return lifecycle in (LifecycleState.ACTIVE, LifecycleState.DORMANT)


def display_label(
    *, confidence_state: str, lifecycle: LifecycleState, human_state: HumanState, contradicted: bool
) -> str:
    """The single word a human sees, derived from the two axes.

    The product vocabulary is a one-dimensional list — observed, candidate,
    confirmed, trusted, stale, archived, forgotten — and it should stay
    that way, because it is how a person explains this to another person.
    The two axes are how the platform *stores* it. Deriving the label here
    keeps both: the schema can express the cases a chain cannot, and nobody
    has to read two columns to understand one row.
    """
    if human_state is HumanState.SUPPRESSED:
        return "suppressed"
    if contradicted:
        return "contradicted"
    if lifecycle is LifecycleState.PURGED:
        return "forgotten"
    if lifecycle is LifecycleState.ARCHIVED:
        return "archived"
    if lifecycle is LifecycleState.DORMANT:
        return "stale"
    return confidence_state


__all__ = [
    "DEFAULT_ARCHIVE_AFTER_DAYS",
    "DEFAULT_DORMANT_AFTER_DAYS",
    "DEFAULT_PURGE_AFTER_DAYS",
    "LifecycleInputs",
    "RetentionPolicy",
    "display_label",
    "is_retrievable",
    "next_lifecycle_state",
    "revive_on_observation",
]
