"""The catalog of things Blink Engage can bill for.

See ``docs/architecture/billing.md``.

**Metrics are code. Pricing is data.**

A billable metric may only exist if the platform actually knows how to
measure it, so metrics are declared here and adding one requires a
release. Administrators configure *prices*, *profiles* and *company
overrides* — all data — but cannot invent a metric. That is not an
arbitrary restriction: a metric an admin could type in would have no
meter behind it, so it would either never charge anything (a price that
silently does nothing) or, worse, invite someone to assume usage is
being captured when it is not.

The catalog is framework-free — no SQLAlchemy, no FastAPI — like
``domain/rbac.py``, ``domain/features.py`` and ``domain/money.py``, so
the pricing engine, the API schemas and the eventual metering consumers
all share one definition without a dependency cycle.

Nothing here mentions *price*. A metric says what is counted and in what
unit; what it costs lives in the pricing tables, effective-dated, and is
resolved separately.
"""

from dataclasses import dataclass
from enum import StrEnum


class MeasurementUnit(StrEnum):
    """What one unit of a metric *is*.

    Carried explicitly rather than implied by the metric name, because
    "price per unit" is meaningless until you know what a unit is —
    and because the answer differs in kind: a conversation is a discrete
    countable thing, a minute is continuous and fractional, a GB-month
    is a rate over time that has to be *sampled* rather than counted.
    A renderer showing "$0.05 / conversation" versus "$0.002 / minute"
    reads this, rather than every caller hardcoding a suffix.
    """

    MESSAGE = "message"
    CONVERSATION = "conversation"
    REPLY = "reply"
    TOKEN = "token"
    IMAGE = "image"
    CHARACTER = "character"
    MINUTE = "minute"
    GIGABYTE = "gigabyte"
    GIGABYTE_MONTH = "gigabyte_month"
    REQUEST = "request"
    EVENT = "event"
    EMAIL = "email"
    NOTIFICATION = "notification"
    #: One active seat for one month. A *level*, not a count of events — see
    #: ``MetricKind.SEAT``.
    AGENT_MONTH = "agent_month"
    BOT_MONTH = "bot_month"
    #: Whatever a customer's own metric counts. Deliberately unitless.
    UNIT = "unit"


class MetricKind(StrEnum):
    """How a period's usage is *derived* from what was measured.

    The billing type, in the sense that matters to the engine: it decides how
    a period aggregate is computed, and getting it wrong is not a rounding
    error but a multiple.

    Written down now, while only one kind is metered, because the mistake this
    prevents is specific and expensive: summing a daily seat count over a
    month bills thirty times the seats. A metric that says what kind it is
    cannot be aggregated the wrong way by accident.
    """

    #: Discrete occurrences, summed. Messages, requests, emails, tokens.
    #: The only kind with a meter today.
    COUNTER = "counter"
    #: Fractional amounts, summed. Phone minutes, gigabytes transferred.
    #: Same aggregation as a counter, different rendering and rounding.
    CONTINUOUS = "continuous"
    #: A level held over time, sampled and averaged rather than summed —
    #: gigabyte-months. Summing samples would bill the same gigabyte once per
    #: sample.
    SAMPLED = "sampled"
    #: A count of active entities in the period: seats, bots. The period value
    #: is the peak (or the average, by contract), never the sum of daily
    #: counts.
    SEAT = "seat"


class MetricAvailability(StrEnum):
    """Whether a measurement engine for this metric exists *today*.

    The guarantee this catalog makes is that every billable metric has a
    valid measurement engine. Declaring a metric before its meter ships
    is useful — it lets the roadmap be visible and the pricing schema be
    designed once — but such a metric must not be priceable, or an
    operator would configure a rate, see no charges, and reasonably
    conclude billing is broken.
    """

    #: A meter exists and emits usage for this metric. Priceable.
    MEASURED = "measured"
    #: Declared, no meter yet. Visible to operators, **not** priceable.
    PLANNED = "planned"
    #: Was measured, and is not any more. **Not** priceable — no new rate may
    #: be set — but everything already recorded stays exactly as it is:
    #: existing rates still resolve, closed periods still price, and old
    #: invoices still reprint. A retired metric is never deleted from this
    #: catalog, because its code appears on documents that must stay
    #: readable years later.
    RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class BillableMetric:
    code: str
    display_name: str
    unit: MeasurementUnit
    description: str
    availability: MetricAvailability
    #: How a period aggregate is derived — see ``MetricKind``. Defaults to
    #: COUNTER because every metered metric today is one, and a wrong default
    #: here would be visible immediately rather than silently.
    kind: MetricKind = MetricKind.COUNTER
    #: **Bump this whenever what the metric counts changes.**
    #:
    #: The code identifies *what* is billed; the version identifies *how
    #: it was measured*. If ``CONVERSATION`` later starts counting a
    #: reopened conversation as a second one, that is a different meaning
    #: for the same code — and a bill reconstructed from historical usage
    #: must reflect what was actually measured at the time, not today's
    #: definition.
    #:
    #: Every usage record and every period snapshot stores the version in
    #: force when it was recorded, so a definition change is invisible to
    #: everything already billed. Changing behaviour *without* bumping
    #: this is the one way to silently rewrite billing history.
    version: int = 1

    @property
    def is_priceable(self) -> bool:
        return self.availability is MetricAvailability.MEASURED


#: Codes are SCREAMING_SNAKE and are a **stable public identifier** —
#: they appear in pricing rows, usage records and invoices, so renaming
#: one silently reprices history. Add metrics; do not rename them.
METRICS: tuple[BillableMetric, ...] = (
    # --- The billing model -------------------------------------------
    BillableMetric(
        code="BILLABLE_MESSAGE",
        display_name="Billable message",
        unit=MeasurementUnit.MESSAGE,
        description=(
            "A customer-facing message on any channel — inbound or outbound, "
            "written by a person, the AI or an automation, in any medium. "
            "Internal notes, system messages and receipts are excluded."
        ),
        availability=MetricAvailability.MEASURED,
    ),
    # --- Retired ------------------------------------------------------
    #
    # Kept, never deleted: these codes appear on issued invoices, closed
    # period snapshots, ledger references and pricing history, all of which
    # must stay readable and must keep pricing exactly the way they were
    # billed. They are simply no longer metered, and no new rate may be set
    # for them.
    #
    # Retired together because they were one billing model: a per-conversation
    # charge with per-AI-feature surcharges on top. The product now charges
    # per customer-facing message, and an AI reply is one of those — the AI's
    # involvement is recorded as an analytics dimension on the billable event
    # rather than as a second charge for the same message.
    BillableMetric(
        code="CONVERSATION",
        display_name="Conversation",
        unit=MeasurementUnit.CONVERSATION,
        description=(
            "A conversation handled on any channel. Retired — billing counts "
            "individual messages, so historical charges remain but nothing new "
            "is metered."
        ),
        availability=MetricAvailability.RETIRED,
    ),
    BillableMetric(
        code="AI_ASSISTED_REPLY",
        display_name="AI-assisted reply",
        unit=MeasurementUnit.REPLY,
        description=(
            "A reply an agent sent with help from the AI Engine. Retired — it "
            "is one billable message, and the AI assistance is an analytics "
            "dimension rather than a surcharge."
        ),
        availability=MetricAvailability.RETIRED,
    ),
    BillableMetric(
        code="AI_AUTOPILOT",
        display_name="AI Autopilot reply",
        unit=MeasurementUnit.REPLY,
        description=(
            "A reply AI Autopilot sent on its own, without an agent. Retired — "
            "it is one billable message, and Autopilot's involvement is an "
            "analytics dimension rather than a surcharge."
        ),
        availability=MetricAvailability.RETIRED,
    ),
    # --- Declared, not yet measurable ------------------------------
    #
    # Every usage dimension this product intends to bill, named now so the
    # pricing schema, the console and the audit trail are designed against the
    # whole shape once rather than grown one refactor at a time. None has a
    # meter, so all are PLANNED and the pricing API refuses to price them: a
    # rate on an unmetered metric charges nothing and looks like working
    # billing, which is the worst of both.
    #
    # They are also a deliberate spread of *kinds* — a counter, a continuous
    # amount, a sampled level and a seat — so the engine is designed against
    # aggregations that genuinely differ rather than four names for "count
    # them up".
    BillableMetric(
        code="AI_TOKEN_INPUT",
        display_name="AI input tokens",
        unit=MeasurementUnit.TOKEN,
        description="A token sent to an AI model, counted as the provider counts it.",
        availability=MetricAvailability.PLANNED,
    ),
    BillableMetric(
        code="AI_TOKEN_OUTPUT",
        display_name="AI output tokens",
        unit=MeasurementUnit.TOKEN,
        description=(
            "A token generated by an AI model. Separate from input because "
            "every provider prices the two differently, and a single combined "
            "metric could not express that."
        ),
        availability=MetricAvailability.PLANNED,
    ),
    BillableMetric(
        code="AI_IMAGE_GENERATION",
        display_name="AI image generation",
        unit=MeasurementUnit.IMAGE,
        description="One image generated by an AI model.",
        availability=MetricAvailability.PLANNED,
    ),
    BillableMetric(
        code="AI_AUDIO_TRANSCRIPTION",
        display_name="AI audio transcription",
        unit=MeasurementUnit.MINUTE,
        description="A minute of audio transcribed. Fractional minutes bill pro rata.",
        availability=MetricAvailability.PLANNED,
        kind=MetricKind.CONTINUOUS,
    ),
    BillableMetric(
        code="AI_AUDIO_SYNTHESIS",
        display_name="AI speech synthesis",
        unit=MeasurementUnit.CHARACTER,
        description=(
            "A character of text synthesised into speech — the unit every "
            "synthesis provider prices in."
        ),
        availability=MetricAvailability.PLANNED,
    ),
    BillableMetric(
        code="STORAGE_GB_MONTH",
        display_name="Storage",
        unit=MeasurementUnit.GIGABYTE_MONTH,
        description=(
            "A gigabyte of stored attachments held for one month. Sampled "
            "rather than counted: summing daily samples would bill the same "
            "gigabyte thirty times."
        ),
        availability=MetricAvailability.PLANNED,
        kind=MetricKind.SAMPLED,
    ),
    BillableMetric(
        code="FILE_BANDWIDTH_GB",
        display_name="File bandwidth",
        unit=MeasurementUnit.GIGABYTE,
        description="A gigabyte of attachment data downloaded or delivered.",
        availability=MetricAvailability.PLANNED,
        kind=MetricKind.CONTINUOUS,
    ),
    BillableMetric(
        code="API_REQUEST",
        display_name="API request",
        unit=MeasurementUnit.REQUEST,
        description="A request to the public API, beyond any included allowance.",
        availability=MetricAvailability.PLANNED,
    ),
    BillableMetric(
        code="WEBHOOK_EVENT",
        display_name="Webhook event",
        unit=MeasurementUnit.EVENT,
        description="An event delivered to a customer's endpoint.",
        availability=MetricAvailability.PLANNED,
    ),
    BillableMetric(
        code="PHONE_MINUTE",
        display_name="Phone minute",
        unit=MeasurementUnit.MINUTE,
        description="A minute of call time. Fractional minutes bill pro rata.",
        availability=MetricAvailability.PLANNED,
        kind=MetricKind.CONTINUOUS,
    ),
    BillableMetric(
        code="SMS_MESSAGE",
        display_name="SMS message",
        unit=MeasurementUnit.MESSAGE,
        description=(
            "An SMS segment sent through a carrier. Distinct from "
            "BILLABLE_MESSAGE, which is channel-agnostic: this one exists to "
            "pass through a carrier cost the platform itself pays."
        ),
        availability=MetricAvailability.PLANNED,
    ),
    BillableMetric(
        code="EMAIL_SENT",
        display_name="Email sent",
        unit=MeasurementUnit.EMAIL,
        description="An email delivered through the platform's own sending domain.",
        availability=MetricAvailability.PLANNED,
    ),
    BillableMetric(
        code="PUSH_NOTIFICATION",
        display_name="Push notification",
        unit=MeasurementUnit.NOTIFICATION,
        description="A push notification delivered to a device.",
        availability=MetricAvailability.PLANNED,
    ),
    BillableMetric(
        code="ACTIVE_AGENT",
        display_name="Active agent",
        unit=MeasurementUnit.AGENT_MONTH,
        description=(
            "An agent seat active during the period. A level, not an event: "
            "the period value is the peak, never the sum of daily counts."
        ),
        availability=MetricAvailability.PLANNED,
        kind=MetricKind.SEAT,
    ),
    BillableMetric(
        code="ACTIVE_BOT",
        display_name="Active bot",
        unit=MeasurementUnit.BOT_MONTH,
        description="An automation or AI bot active during the period.",
        availability=MetricAvailability.PLANNED,
        kind=MetricKind.SEAT,
    ),
    BillableMetric(
        code="CUSTOM_METRIC",
        display_name="Custom metric",
        unit=MeasurementUnit.UNIT,
        description=(
            "A dimension a deployment meters for itself. Deliberately "
            "unitless, and deliberately a single code: a metric per customer "
            "would make the catalog data, and metrics are code so that every "
            "priced thing provably has a meter."
        ),
        availability=MetricAvailability.PLANNED,
    ),
)

_BY_CODE: dict[str, BillableMetric] = {metric.code: metric for metric in METRICS}

METRIC_CODES: frozenset[str] = frozenset(_BY_CODE)


def get_metric(code: str) -> BillableMetric | None:
    return _BY_CODE.get(code)


def is_known_metric(code: str) -> bool:
    return code in _BY_CODE


def is_priceable(code: str) -> bool:
    """Whether a **new** price may be configured for this metric.

    False for an unknown code, a ``PLANNED`` one and a ``RETIRED`` one. The
    pricing API checks this rather than merely checking existence, so a rate
    can never be attached to something nothing measures — and so nobody sets
    a rate on a retired metric that would never charge anything.

    Deliberately *not* consulted on read: a retired metric's existing rates
    must keep resolving, or a closed period would fail to reprice and an
    invoice would fail to reprint.
    """
    metric = _BY_CODE.get(code)
    return metric is not None and metric.is_priceable


def priceable_metrics() -> tuple[BillableMetric, ...]:
    return tuple(metric for metric in METRICS if metric.is_priceable)


def retired_metrics() -> tuple[BillableMetric, ...]:
    """Metrics that were once metered. Surfaced so a console can show a
    company's historical charges with a label rather than an unexplained
    code."""
    return tuple(
        metric for metric in METRICS if metric.availability is MetricAvailability.RETIRED
    )


def is_retired(code: str) -> bool:
    metric = get_metric(code)
    return metric is not None and metric.availability is MetricAvailability.RETIRED


__all__ = [
    "METRICS",
    "METRIC_CODES",
    "BillableMetric",
    "MeasurementUnit",
    "MetricAvailability",
    "get_metric",
    "is_known_metric",
    "is_priceable",
    "is_retired",
    "priceable_metrics",
    "retired_metrics",
]
