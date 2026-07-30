"""Recording one billable message.

See ``docs/architecture/billing.md``.

Sits between the meter and the usage engine, and owns one transaction: a
customer-facing message produces **one** immutable billable event and **one**
usage record, together or not at all.

Why both, rather than a usage record alone: the usage record is the quantity
that gets billed, and the billable event is the evidence for it — which
message, on which channel, in which conversation, from whom. A disputed
invoice is answered by walking the events; a total is answered by summing the
records. Keeping them separate means the billing path stays a simple count
while the audit path keeps every dimension.

**The event is written even when nothing is billed.** A message that arrives
for a period that has already closed is recorded as evidence with no usage
record attached: the arrival is a fact, and the late count on the period is
the honest way to surface it. Silently billing it into the open period would
move revenue between months.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from blinkengage.application.services.usage_service import UsageService
from blinkengage.core.logging import get_logger
from blinkengage.domain.billable_events import (
    BillableMessage,
    MessageDirection,
    MessageOrigin,
    is_billable,
)
from blinkengage.domain.usage import UsageRecordSource
from blinkengage.infrastructure.database.models.billable_event import BillableEvent
from blinkengage.infrastructure.repositories.billable_event_repository import (
    BillableEventRepository,
)

logger = get_logger(__name__)

#: The metric every billable message counts towards. One code, no per-channel
#: and no per-origin variants — billing is channel-agnostic, and an AI reply is
#: a message like any other.
METRIC_CODE = "BILLABLE_MESSAGE"

#: One message is one unit. Named rather than inlined so the intent is visible:
#: a long message is not two, and a message with five attachments is not six.
_ONE = Decimal(1)


@dataclass(frozen=True, slots=True)
class BillableOutcome:
    """What recording one message did.

    ``reason`` is one of ``recorded``, ``duplicate``, ``not_billable`` or
    ``period_closed``. Every one of them is a success as far as the event bus
    is concerned: at-least-once delivery makes duplicates ordinary, and raising
    on one would retry it forever.
    """

    recorded: bool
    reason: str
    event_id: uuid.UUID | None = None
    usage_record_id: uuid.UUID | None = None


class BillableEventService:
    def __init__(
        self, *, events: BillableEventRepository, usage: UsageService
    ) -> None:
        self._events = events
        self._usage = usage

    async def record_message(
        self,
        *,
        company_id: uuid.UUID,
        message: BillableMessage,
        occurred_at: datetime,
        customer_id: uuid.UUID | None = None,
    ) -> BillableOutcome:
        """Records one message as billable, if it is.

        Idempotent on ``message_id``: the existing event is found and nothing
        is written. Checked here *and* enforced by a unique constraint, because
        two workers can pass the check at the same moment and only the database
        can settle that.
        """
        if not is_billable(message):
            # Not an error and not worth a log line at info: the meter is bound
            # to message events, and a system message is simply not one of the
            # billable ones.
            return BillableOutcome(recorded=False, reason="not_billable")

        message_uuid = uuid.UUID(message.message_id)
        existing = await self._events.get_by_message(message_uuid)
        if existing is not None:
            return BillableOutcome(
                recorded=False,
                reason="duplicate",
                event_id=existing.id,
                usage_record_id=existing.usage_record_id,
            )

        outcome = await self._usage.record(
            company_id=company_id,
            metric_code=METRIC_CODE,
            quantity=_ONE,
            occurred_at=occurred_at,
            # Derived from the message itself, never from a timestamp or a
            # random value — that is what makes a redelivery a no-op.
            idempotency_key=f"{METRIC_CODE}:{message.message_id}",
            source=UsageRecordSource.METER,
            source_reference=message.message_id,
        )
        if outcome.period_id is None:
            # No period could be established at all — a company deleted
            # mid-flight, or a clock so far off that no period covers the
            # instant. Nothing to attach evidence to; reported, not raised.
            logger.warning(
                "billable_message_unattributable",
                company_id=str(company_id),
                message_id=message.message_id,
                reason=outcome.reason,
            )
            return BillableOutcome(recorded=False, reason=outcome.reason)

        event = await self._events.add(
            BillableEvent(
                company_id=company_id,
                billing_period_id=outcome.period_id,
                message_id=message_uuid,
                conversation_id=uuid.UUID(message.conversation_id),
                customer_id=customer_id,
                direction=message.direction,
                origin=message.origin,
                channel_type=message.channel_type,
                message_type=message.message_type,
                occurred_at=occurred_at,
                # None when the period had already closed: the message is
                # evidence, and deliberately not a charge.
                usage_record_id=outcome.record_id,
            )
        )
        return BillableOutcome(
            recorded=outcome.recorded,
            reason=outcome.reason,
            event_id=event.id,
            usage_record_id=outcome.record_id,
        )

    # --- Analytics --------------------------------------------------
    #
    # Channel and origin breakdowns. Read by reports and the dashboard, and by
    # nothing that prices — see ``domain/billable_events.py`` on why billing
    # stays channel-agnostic.

    async def by_channel(
        self, *, company_id: uuid.UUID, start: datetime, end: datetime
    ) -> list[tuple[str, int]]:
        return await self._events.by_channel(company_id=company_id, start=start, end=end)

    async def by_origin(
        self, *, company_id: uuid.UUID, start: datetime, end: datetime
    ) -> list[tuple[str, int]]:
        return await self._events.by_origin(company_id=company_id, start=start, end=end)

    async def by_direction(
        self, *, company_id: uuid.UUID, start: datetime, end: datetime
    ) -> list[tuple[str, int]]:
        return await self._events.by_direction(company_id=company_id, start=start, end=end)


__all__ = [
    "METRIC_CODE",
    "BillableEventService",
    "BillableOutcome",
    "MessageDirection",
    "MessageOrigin",
]
