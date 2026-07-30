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
    MINUTE = "minute"
    GIGABYTE_MONTH = "gigabyte_month"


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
    # Both are real roadmap metrics with no meter in this codebase:
    # there is no voice channel, and nothing samples attachment storage.
    # They are listed so the pricing schema is designed against the full
    # shape of the problem (a fractional unit and a sampled-rate unit,
    # neither of which a per-conversation count exercises) — but they
    # are PLANNED, so the pricing API refuses to price them.
    BillableMetric(
        code="VOICE_MINUTE",
        display_name="Voice minute",
        unit=MeasurementUnit.MINUTE,
        description="A minute of voice call time. Fractional minutes are billed pro rata.",
        availability=MetricAvailability.PLANNED,
    ),
    BillableMetric(
        code="STORAGE_GB",
        display_name="Storage",
        unit=MeasurementUnit.GIGABYTE_MONTH,
        description="A gigabyte of stored attachments, held for one month.",
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
