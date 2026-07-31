"""Executable scenarios, and a score nobody is allowed to hand out.

The last piece of the SDK. A connector declares what it supports and how to
diagnose it; this is where it is made to *prove* it, against a real channel,
and where the proof becomes a number.

Three properties the design is built around, each because the obvious version
is wrong:

**"Not supported" must not count against a connector.** SMS cannot send
media. Scoring that as a failure would give every honest connector a worse
score than a dishonest one, and within a week every manifest would claim
everything. So the denominator is what the connector *said it could do* —
which is exactly the manifest that already exists, so the scenario list is
derived from the feature matrix rather than declared a second time.

**A score with nothing behind it is worse than no score.** Three passing
scenarios out of eleven is not 100%; it is 100% of very little. Certification
therefore carries *coverage* alongside the score, and a grade that requires
both — otherwise "96%, Production Ready" is a sentence a suite can produce by
running almost nothing.

**Nothing here may send a message to a real customer.** A live channel is
somebody's WhatsApp number, and a certification run that texted their
customers to prove it could would be the worst possible way to discover this
feature. Scenarios that would emit anything declare a target and are
``SKIPPED`` without one — never guessed at, never sent to the last person who
wrote in.

The score is computed and cannot be set. There is no field to assign, no
override, and no way to certify a connector except by running it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

from blinkengage.domain.connector_lifecycle import ChannelFeature, Direction


class ScenarioKind(StrEnum):
    """One thing a connector can be made to demonstrate.

    A closed set, so a certification report has the same rows for every
    channel and two connectors cannot name one behaviour differently.
    """

    AUTHENTICATION = "authentication"
    SEND_MESSAGE = "send_message"
    RECEIVE_MESSAGE = "receive_message"
    MEDIA_UPLOAD = "media_upload"
    MEDIA_DOWNLOAD = "media_download"
    READ_RECEIPT = "read_receipt"
    TYPING_INDICATOR = "typing_indicator"
    WEBHOOK_DELIVERY = "webhook_delivery"
    TOKEN_REFRESH = "token_refresh"
    DISCONNECT = "disconnect"
    RECONNECT = "reconnect"


class Outcome(StrEnum):
    """How a scenario came out.

    Five values, and the distinctions between the last three are the whole
    reason certification means anything:

    - ``NOT_SUPPORTED`` — the connector never claimed this. Excluded from the
      score entirely; a channel with no typing indicator is not a worse
      channel, it is a different one.
    - ``SKIPPED`` — claimed, but not executed here: no target to send to, no
      credentials, a destructive step nobody opted into. Counts against
      *coverage* but not against the *score*, because an unexecuted test is
      an unanswered question rather than a failure.
    - ``WARNING`` — it worked, with something worth saying. Counts as a
      partial pass; a connector that always warns should not certify as
      cleanly as one that never does.
    """

    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"
    SKIPPED = "skipped"
    NOT_SUPPORTED = "not_supported"


#: Which feature makes a scenario applicable. The link that stops the test
#: suite being a second declaration of what a connector supports — the
#: manifest already said, so the suite reads it.
#:
#: A scenario with no entry applies to every connector: authentication,
#: disconnect and reconnect are not features, they are the lifecycle every
#: connector has by existing.
SCENARIO_FEATURE: dict[ScenarioKind, tuple[ChannelFeature, Direction]] = {
    ScenarioKind.SEND_MESSAGE: (ChannelFeature.SEND_MESSAGES, Direction.OUTBOUND),
    ScenarioKind.RECEIVE_MESSAGE: (ChannelFeature.RECEIVE_MESSAGES, Direction.INBOUND),
    ScenarioKind.MEDIA_UPLOAD: (ChannelFeature.MEDIA, Direction.OUTBOUND),
    ScenarioKind.MEDIA_DOWNLOAD: (ChannelFeature.MEDIA, Direction.INBOUND),
    ScenarioKind.READ_RECEIPT: (ChannelFeature.READ_RECEIPTS, Direction.OUTBOUND),
    ScenarioKind.TYPING_INDICATOR: (
        ChannelFeature.TYPING_INDICATORS,
        Direction.OUTBOUND,
    ),
}

#: Scenarios that would put something in front of a real person, or change
#: something a customer would notice. They need an explicit target and are
#: skipped without one — a certification run must never be the reason a
#: customer receives a message.
EMITS_TO_A_CUSTOMER: frozenset[ScenarioKind] = frozenset(
    {
        ScenarioKind.SEND_MESSAGE,
        ScenarioKind.MEDIA_UPLOAD,
        ScenarioKind.READ_RECEIPT,
        ScenarioKind.TYPING_INDICATOR,
    }
)

#: Scenarios that change the channel's own state with the provider. Run only
#: when asked for by name: re-registering a webhook mid-certification would
#: leave a working channel in whatever state the run finished in.
MUTATES_THE_CHANNEL: frozenset[ScenarioKind] = frozenset(
    {ScenarioKind.DISCONNECT, ScenarioKind.RECONNECT, ScenarioKind.TOKEN_REFRESH}
)


def supports_scenario(
    kind: ScenarioKind, supported: tuple[tuple[ChannelFeature, Direction], ...]
) -> bool:
    """Whether a connector claiming these features claims this scenario.

    Direction matters and is the point: a connector that receives media and
    cannot send it claims ``MEDIA_DOWNLOAD`` and not ``MEDIA_UPLOAD``, so
    the upload scenario reports ``NOT_SUPPORTED`` rather than failing — which
    is exactly what the direction field was added to make possible.
    """
    required = SCENARIO_FEATURE.get(kind)
    if required is None:
        return True
    feature, direction = required
    for declared_feature, declared_direction in supported:
        if declared_feature is not feature:
            continue
        if declared_direction is Direction.BOTH or declared_direction is direction:
            return True
    return False


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    """One executed scenario."""

    kind: ScenarioKind
    outcome: Outcome
    #: Wall-clock, so a connector that passes slowly is visibly different
    #: from one that passes. Zero for anything not executed.
    duration_ms: int = 0
    #: A translation key. Never a sentence — a certification report read by a
    #: partner in Amman must be readable in Arabic.
    detail_key: str | None = None
    params: dict[str, str] = field(default_factory=dict)
    #: Anything the run learned that is worth keeping: a provider message
    #: id, a status code, a redacted error. Diagnostic depth, not copy.
    diagnostics: dict[str, str] = field(default_factory=dict)

    @property
    def executed(self) -> bool:
        return self.outcome in {Outcome.PASS, Outcome.FAIL, Outcome.WARNING}


class Grade(StrEnum):
    """What a score means, in words an administrator can act on."""

    PRODUCTION_READY = "production_ready"
    NEEDS_ATTENTION = "needs_attention"
    NOT_READY = "not_ready"
    #: Too little was executed to say anything. Distinct from a bad score,
    #: because "we do not know" and "we know it is bad" lead to different
    #: next actions.
    INCONCLUSIVE = "inconclusive"


#: A scenario that only warned still worked. Weighted below a clean pass so a
#: connector that always warns cannot certify identically to one that never
#: does, and above a failure because it did the thing.
WARNING_WEIGHT = 0.5

#: How much of what a connector claims must actually have run before a grade
#: is meaningful. Below this the report is ``INCONCLUSIVE`` whatever the
#: score — "96%, Production Ready" from two executed scenarios is a sentence
#: no suite should be able to produce.
MINIMUM_COVERAGE = 0.6

#: Score at or above which a connector is production ready, given coverage.
PRODUCTION_SCORE = 0.9
ATTENTION_SCORE = 0.7


@dataclass(frozen=True, slots=True)
class Certification:
    """A score, and everything needed to distrust it.

    Constructed only by :func:`certify`. There is no setter, no override and
    no field an operator can write — a certification that could be assigned
    is a certification that means whatever the person assigning it wanted.
    """

    score: float
    grade: Grade
    #: Of what the connector claims, how much actually ran. The number that
    #: stops a high score from being cheap.
    coverage: float
    passed: int
    failed: int
    warned: int
    skipped: int
    not_supported: int

    @property
    def percent(self) -> int:
        return round(self.score * 100)


def certify(results: tuple[ScenarioResult, ...]) -> Certification:
    """Compute the score. The only way one is ever produced.

    The denominator is what the connector *claimed*, so declaring less does
    not buy a better score and declaring more does not either — it buys more
    scenarios that have to pass.
    """
    passed = sum(1 for r in results if r.outcome is Outcome.PASS)
    failed = sum(1 for r in results if r.outcome is Outcome.FAIL)
    warned = sum(1 for r in results if r.outcome is Outcome.WARNING)
    skipped = sum(1 for r in results if r.outcome is Outcome.SKIPPED)
    not_supported = sum(1 for r in results if r.outcome is Outcome.NOT_SUPPORTED)

    executed = passed + failed + warned
    claimed = executed + skipped

    score = (passed + warned * WARNING_WEIGHT) / executed if executed else 0.0
    coverage = executed / claimed if claimed else 0.0

    if claimed == 0:
        # A connector claiming nothing certifiable. Not a failure — Web Chat
        # legitimately has almost nothing to prove against a provider — but
        # not a pass either, and saying so is more useful than a 0%.
        grade = Grade.INCONCLUSIVE
    elif coverage < MINIMUM_COVERAGE:
        grade = Grade.INCONCLUSIVE
    elif failed:
        # Any outright failure keeps it out of production, whatever the
        # arithmetic says. Nine passes and one broken authentication is not
        # a 90% channel, it is a channel that does not work.
        grade = Grade.NOT_READY if score < ATTENTION_SCORE else Grade.NEEDS_ATTENTION
    elif score >= PRODUCTION_SCORE:
        grade = Grade.PRODUCTION_READY
    elif score >= ATTENTION_SCORE:
        grade = Grade.NEEDS_ATTENTION
    else:
        grade = Grade.NOT_READY

    return Certification(
        score=round(score, 4),
        grade=grade,
        coverage=round(coverage, 4),
        passed=passed,
        failed=failed,
        warned=warned,
        skipped=skipped,
        not_supported=not_supported,
    )


@dataclass(frozen=True, slots=True)
class Compatibility:
    """Whether this connector is drifting out of date.

    Everything an administrator needs to answer "should I be worried about
    this one?" without reading a changelog.
    """

    platform_version: str
    connector_version: str
    provider_api_version: str
    #: When the suite last actually ran. ``None`` means never — which is the
    #: honest state for a connector nobody has certified, and is why this is
    #: nullable rather than defaulted to now.
    last_verified: datetime | None = None
    #: When the provider retires the API version this connector speaks, where
    #: the provider publishes one. Meta deprecates Graph versions on a
    #: schedule; Telegram's Bot API has no such concept, and ``None`` says so
    #: rather than inventing a date.
    supported_until: date | None = None

    def expiring_within(self, days: int, *, today: date) -> bool:
        if self.supported_until is None:
            return False
        return (self.supported_until - today).days <= days


@dataclass(frozen=True, slots=True)
class CertificationReport:
    """One certification run, whole."""

    channel_type: str
    results: tuple[ScenarioResult, ...]
    certification: Certification
    compatibility: Compatibility
    ran_at: datetime
    #: Total wall-clock, which is not the sum of the parts when scenarios
    #: run concurrently — and is the number an operator actually waited.
    duration_ms: int = 0


__all__ = [
    "ATTENTION_SCORE",
    "EMITS_TO_A_CUSTOMER",
    "MINIMUM_COVERAGE",
    "MUTATES_THE_CHANNEL",
    "PRODUCTION_SCORE",
    "SCENARIO_FEATURE",
    "WARNING_WEIGHT",
    "Certification",
    "CertificationReport",
    "Compatibility",
    "Grade",
    "Outcome",
    "ScenarioKind",
    "ScenarioResult",
    "certify",
    "supports_scenario",
]
