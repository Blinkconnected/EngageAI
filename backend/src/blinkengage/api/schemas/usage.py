"""Request/response schemas for the usage engine.

Amounts and quantities are serialized as **strings**, for the same
reason prices are: a JSON number becomes a float in the browser and
reintroduces the drift `Decimal` exists to prevent.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, PlainSerializer

from blinkengage.domain.usage import BillingPeriodStatus, UsageRecordSource

Quantity = Annotated[Decimal, PlainSerializer(str, return_type=str)]


class UsageLineResponse(BaseModel):
    """A live, unpriced aggregate of the open period."""

    metric_code: str
    metric_version: int
    display_name: str
    unit: str
    quantity: Quantity
    record_count: int


class BillingPeriodResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    period_start: datetime
    period_end: datetime
    status: BillingPeriodStatus
    closed_at: datetime | None
    total_amount: Quantity | None
    currency: str | None
    due_date: datetime | None
    late_record_count: int


class CurrentUsageResponse(BaseModel):
    """The open period and what has accrued so far.

    Deliberately carries no money. An estimate is a different thing from
    a charge, and putting a second, subtly-different number beside the
    frozen ones is how a customer ends up disputing a bill that is
    correct.
    """

    period: BillingPeriodResponse | None
    lines: list[UsageLineResponse]


class SnapshotLineResponse(BaseModel):
    """A frozen line of a closed period — the shape an invoice line
    copies verbatim."""

    model_config = ConfigDict(from_attributes=True)

    metric_code: str
    metric_version: int
    metric_display_name: str
    unit: str
    quantity: Quantity
    unit_amount: Quantity
    currency: str
    subtotal: Quantity
    #: The exact pricing row that produced ``unit_amount`` — the audit
    #: chain from a charge back to the decision that set it.
    rate_id: uuid.UUID | None
    unpriced: bool
    record_count: int


class PeriodSnapshotResponse(BaseModel):
    period: BillingPeriodResponse
    lines: list[SnapshotLineResponse]


class RecordUsageRequest(BaseModel):
    """A manual correction or credit, entered by a platform operator.

    Meters do not use this — they consume events. It exists so an
    operator can correct a measurement error without editing rows by
    hand, and every such entry is marked ``MANUAL`` and carries a note.
    """

    company_id: uuid.UUID
    metric_code: str
    quantity: Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=6)]
    occurred_at: AwareDatetime
    #: Required: an idempotency key that the caller controls, so a
    #: retried request cannot double-count.
    idempotency_key: str = Field(min_length=1, max_length=200)
    note: str = Field(min_length=1, max_length=2000)


class RecordUsageResponse(BaseModel):
    recorded: bool
    reason: str
    record_id: uuid.UUID | None


class ClosePeriodResponse(BaseModel):
    period_id: uuid.UUID
    already_closed: bool
    line_count: int
    total_amount: Quantity
    unpriced_metrics: list[str]


class UsageRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    metric_code: str
    metric_version: int
    quantity: Quantity
    occurred_at: datetime
    source: UsageRecordSource
    source_reference: str | None
    note: str | None
