"""How much the platform believes a fact, and which way that is moving.

Pure — no repository, no clock passed implicitly. Every input is supplied
by the caller, so the same inputs always produce the same answer and the
computation is reproducible months later from the evidence still on the
row. That is the property that lets somebody ask *"why is this 0.31 now
when it was 0.88 in March?"* and get an answer rather than a shrug.

**Confidence is computed, never claimed.** The platform's existing habit
is to ask the model — ``suggest_autopilot_reply`` parses a ``CONFIDENCE:``
line, and ``ai-engine.md`` concedes it is "still ultimately the model's own
opinion". That is defensible for one reply a threshold gates. It is not
defensible for a fact that will be quoted to thousands of customers,
because a model's self-assessment is uncorrelated with whether a claim is
true *of this company* — the one thing the model cannot know.

So every input here is something the platform observed:

- how much support there is, and **how broadly** it is spread;
- how good the outcomes of the supporting conversations were;
- how often the fact has been contradicted;
- how long ago it was last seen.

Breadth is weighted separately from volume on purpose. Forty repetitions
by one agent to one customer is one person's habit observed forty times;
six agents converging independently is a practice. A formula that cannot
tell those apart will confidently promote the first into company policy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from blinkengage.domain.memory import ConfidenceDirection, ConfidenceState

# --- Weights ---------------------------------------------------------------
#
# Named constants rather than inline literals, and a test asserts each one
# actually moves the output. A declared input the function ignores is a
# rule that silently never takes effect — the same discipline the customer
# context fingerprint already uses.

W_SUPPORT = 0.55
W_DISTINCT_CUSTOMERS = 0.95
W_DISTINCT_AGENTS = 0.85
W_OUTCOME = 1.10
W_CONTRADICTION = 1.40

#: Shifts the sigmoid so a single observation lands low rather than at 0.5.
#: Without it every brand-new fact would start out half-believed.
BIAS = -2.30

#: How long a fact keeps most of its confidence without being re-observed,
#: per fact type. A single global half-life would either expire stable
#: facts or preserve stale ones, and both failures are silent.
DEFAULT_HALF_LIFE_DAYS = 120.0
HALF_LIFE_DAYS: dict[str, float] = {
    # Vocabulary barely moves. A company that calls its mid tier "Silver"
    # still does next year, and forgetting it costs retrieval its ability
    # to recognise the word at all.
    "terminology": 1460.0,
    # Seasonal patterns are *about* a yearly cycle. Decaying them faster
    # than the cycle they describe would expire every pattern before its
    # season came round again.
    "seasonal_pattern": 400.0,
    "channel_preference": 240.0,
    "preferred_language": 365.0,
    "communication_style": 240.0,
    "contact_preference": 365.0,
    "product_owned": 180.0,
    "relationship_event": 180.0,
    "past_issue": 120.0,
    "important_note": 365.0,
    # A promise has a due date. Nothing about it should linger.
    "promise_made": 30.0,
    "sentiment_trend": 60.0,
    "recurring_issue": 90.0,
    "successful_solution": 150.0,
    "objection": 150.0,
    "process_observation": 120.0,
    # Experience claims are about what works *now*. A market moves.
    "effective_response": 90.0,
    "ineffective_response": 90.0,
    "escalation_trigger": 90.0,
    "effective_workflow": 120.0,
    "fcr_pattern": 90.0,
    "csat_driver": 90.0,
    "handling_time_pattern": 90.0,
}

# --- State thresholds, with hysteresis -------------------------------------
#
# Promotion and demotion thresholds differ deliberately. A fact hovering on
# a boundary would otherwise flap between states on every nightly
# recompute, and each flap is a state change something downstream reacts
# to — a notification, an analytics row, a retrieval eligibility flip.
PROMOTE_TO_CANDIDATE = 0.30
PROMOTE_TO_CONFIRMED = 0.55
PROMOTE_TO_TRUSTED = 0.80

DEMOTE_FROM_TRUSTED = 0.72
DEMOTE_FROM_CONFIRMED = 0.47
DEMOTE_FROM_CANDIDATE = 0.22

#: A fact may not be CONFIRMED or better on inference alone, whatever the
#: arithmetic says. Corroboration means a human, a system of record, or a
#: measured outcome — never repetition, which is what a customer asserting
#: the same thing repeatedly would otherwise buy.
_CORROBORATION_CEILING = ConfidenceState.CANDIDATE


@dataclass(frozen=True)
class ConfidenceInputs:
    """Everything the computation is allowed to look at.

    A frozen record rather than a long parameter list, so a caller that
    forgets an input gets a type error and every call site is visibly
    supplying the same shape.
    """

    support_count: int
    distinct_customer_count: int
    distinct_agent_count: int
    contradiction_count: int
    last_observed_at: datetime
    now: datetime
    fact_type: str
    #: 0.0–1.0, or ``None`` when nothing measured the outcomes of the
    #: supporting conversations. ``None`` is neutral rather than zero: most
    #: conversations have no CSAT, and treating "unmeasured" as "bad" would
    #: mean only the surveyed minority could ever be believed.
    outcome_quality: float | None = None
    #: Whether any evidence corroborates rather than merely repeats.
    has_corroboration: bool = False


def half_life_days(fact_type: str) -> float:
    return HALF_LIFE_DAYS.get(fact_type, DEFAULT_HALF_LIFE_DAYS)


def recency_factor(*, last_observed_at: datetime, now: datetime, fact_type: str) -> float:
    """Exponential decay on age, per fact type.

    A fact observed in the future — a clock skew, an imported row with a
    bad timestamp — decays by zero rather than amplifying. Amplifying would
    let a bad timestamp manufacture confidence.
    """
    age_days = max(0.0, (now - last_observed_at).total_seconds() / 86400.0)
    return float(0.5 ** (age_days / half_life_days(fact_type)))


def decayed_confidence(
    *,
    stored: float,
    computed_at: datetime | None,
    now: datetime,
    fact_type: str,
) -> float:
    """The confidence a reader should act on, right now.

    The stored column is a **cache**: it was correct at
    ``confidence_computed_at`` and has been decaying since. A reader that
    trusted it directly would rank a fact nobody has re-observed in a year
    exactly as it ranked the day it was last swept — and at any real
    corpus size the sweep cannot revisit every row often enough for that
    gap to be small.

    So decay is finished here, at read time. This is the correctness half
    of the fix for the sweep's throughput ceiling: the sweep keeps the
    cache warm and bounds how much work this has to do, but a stale cache
    now produces a *slightly conservative* number rather than a wrong one.

    ``computed_at`` of ``None`` means never swept, so there is nothing to
    decay from and the stored value stands.
    """
    if computed_at is None:
        return max(0.0, min(1.0, stored))
    elapsed_days = max(0.0, (now - computed_at).total_seconds() / 86400.0)
    factor = float(0.5 ** (elapsed_days / half_life_days(fact_type)))
    return max(0.0, min(1.0, stored * factor))


def compute_confidence(inputs: ConfidenceInputs) -> float:
    """The number, in ``[0, 1]``.

    Logarithmic in the counts because the tenth observation genuinely tells
    you less than the second, and linear growth would let a high-volume
    topic reach certainty on nothing but traffic.
    """
    outcome = 0.0 if inputs.outcome_quality is None else (inputs.outcome_quality - 0.5) * 2.0

    raw = (
        BIAS
        + W_SUPPORT * math.log1p(max(0, inputs.support_count))
        + W_DISTINCT_CUSTOMERS * math.log1p(max(0, inputs.distinct_customer_count))
        + W_DISTINCT_AGENTS * math.log1p(max(0, inputs.distinct_agent_count))
        + W_OUTCOME * outcome
        - W_CONTRADICTION * math.log1p(max(0, inputs.contradiction_count))
    )

    belief = 1.0 / (1.0 + math.exp(-raw))
    decayed = belief * recency_factor(
        last_observed_at=inputs.last_observed_at,
        now=inputs.now,
        fact_type=inputs.fact_type,
    )
    return max(0.0, min(1.0, decayed))


def next_confidence_state(
    *,
    current: ConfidenceState,
    confidence: float,
    has_corroboration: bool,
) -> ConfidenceState:
    """Where the fact sits on the belief axis, with hysteresis.

    Demotion thresholds sit below promotion thresholds, so crossing back
    and forth requires a real move rather than a rounding difference.
    """
    if confidence >= PROMOTE_TO_TRUSTED:
        target = ConfidenceState.TRUSTED
    elif confidence >= PROMOTE_TO_CONFIRMED:
        target = ConfidenceState.CONFIRMED
    elif confidence >= PROMOTE_TO_CANDIDATE:
        target = ConfidenceState.CANDIDATE
    else:
        target = ConfidenceState.OBSERVED

    order = [
        ConfidenceState.OBSERVED,
        ConfidenceState.CANDIDATE,
        ConfidenceState.CONFIRMED,
        ConfidenceState.TRUSTED,
    ]
    if order.index(target) < order.index(current):
        # Falling: only demote once past the *lower* threshold.
        floor = {
            ConfidenceState.TRUSTED: DEMOTE_FROM_TRUSTED,
            ConfidenceState.CONFIRMED: DEMOTE_FROM_CONFIRMED,
            ConfidenceState.CANDIDATE: DEMOTE_FROM_CANDIDATE,
            ConfidenceState.OBSERVED: 0.0,
        }[current]
        if confidence >= floor:
            target = current

    if not has_corroboration and order.index(target) > order.index(_CORROBORATION_CEILING):
        # The structural defence against belief-by-repetition. Arithmetic
        # cannot lift an uncorroborated fact past CANDIDATE however many
        # times it has been observed.
        target = _CORROBORATION_CEILING

    return target


@dataclass(frozen=True)
class DirectionInputs:
    """Evidence movement over a window, with decay already excluded.

    Deliberately *not* two confidence readings. Confidence includes recency
    decay, so differencing it reports FALLING for every fact that is merely
    quiet — which is most facts — and the column would become a slower,
    noisier restatement of ``DORMANT``.
    """

    supporting_delta: int
    contradicting_delta: int
    #: How many recomputes are in the window. Direction on one sample is
    #: not a trend, and saying so is better than guessing.
    samples: int


#: Below this, a change is noise rather than a trend.
_DIRECTION_FLOOR = 1
_MIN_SAMPLES = 2


def compute_direction(inputs: DirectionInputs) -> ConfidenceDirection:
    """Which way belief is moving, from the evidence stream."""
    if inputs.samples < _MIN_SAMPLES:
        return ConfidenceDirection.UNKNOWN

    supporting = max(0, inputs.supporting_delta)
    contradicting = max(0, inputs.contradicting_delta)

    if supporting >= _DIRECTION_FLOOR and contradicting >= _DIRECTION_FLOOR:
        # Both growing. The company is being inconsistent about something,
        # which is a more actionable finding than either direction alone —
        # two departments quoting different lead times produce exactly
        # this, and it is usually the first time anybody notices.
        return ConfidenceDirection.CONTESTED
    if contradicting >= _DIRECTION_FLOOR:
        return ConfidenceDirection.FALLING
    if supporting >= _DIRECTION_FLOOR:
        return ConfidenceDirection.RISING
    return ConfidenceDirection.STABLE


__all__ = [
    "BIAS",
    "DEFAULT_HALF_LIFE_DAYS",
    "DEMOTE_FROM_CANDIDATE",
    "DEMOTE_FROM_CONFIRMED",
    "DEMOTE_FROM_TRUSTED",
    "HALF_LIFE_DAYS",
    "PROMOTE_TO_CANDIDATE",
    "PROMOTE_TO_CONFIRMED",
    "PROMOTE_TO_TRUSTED",
    "W_CONTRADICTION",
    "W_DISTINCT_AGENTS",
    "W_DISTINCT_CUSTOMERS",
    "W_OUTCOME",
    "W_SUPPORT",
    "ConfidenceInputs",
    "DirectionInputs",
    "compute_confidence",
    "decayed_confidence",
    "compute_direction",
    "half_life_days",
    "next_confidence_state",
    "recency_factor",
]
