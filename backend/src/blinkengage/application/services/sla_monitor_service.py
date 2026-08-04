"""Detects SLA breaches (and, since the SLA Builder, approaching-breach
warnings) via a periodic sweep, not a per-conversation timer — see
``docs/architecture/queues-routing.md`` decision #4 and
``docs/architecture/sla.md``.

A conversation's *effective* SLA config comes from its queue's assigned
``SlaPolicy`` (business-hours-aware deadlines, a warning threshold,
escalation rules) if one is set, falling back unchanged to the queue's
own legacy ``first_response_target_minutes``/``resolution_target_minutes``
fields (plain wall-clock math, no warning, no escalation) if not — see
``Queue.sla_policy_id``'s docstring. Publishes ``conversation.sla_warning``
once per breach type when a policy's warning threshold is crossed, and
``conversation.sla_breached`` exactly once per breach type either way.

Escalation rules execute directly against ``ConversationService``/
``NotificationService`` — the same functions a Workflow Engine action
would call — rather than generating ``WorkflowDefinition`` rows, since no
generic workflow-authoring UI exists to reuse and this keeps a bad
policy's escalation config from being able to affect anything but its
own conversation (one rule's failure is caught and logged, never allowed
to abort the sweep for every other conversation).
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.application.services.conversation_service import ConversationService
from blinkengage.application.services.notification_service import NotificationService
from blinkengage.core.logging import get_logger
from blinkengage.domain.business_hours import (
    BusinessHoursSchedule,
    add_business_minutes,
    resolve_schedule,
)
from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.lifecycle import ACTIVE, AWAITING_OTHERS
from blinkengage.domain.ownership import OwnershipReason
from blinkengage.infrastructure.database.models.company import Company
from blinkengage.infrastructure.database.models.conversation import (
    Conversation,
)
from blinkengage.infrastructure.database.models.queue import Queue
from blinkengage.infrastructure.database.models.sla import Holiday, SlaPolicy

logger = get_logger(__name__)

#: The statuses in which an SLA clock is still running. Built from the
#: lifecycle's own sets rather than listed here, so a status added later
#: cannot quietly fall outside every SLA — the failure mode of a hand-kept
#: tuple, which looks correct right up until somebody adds the ninth state.
#:
#: ``WAITING_CUSTOMER`` is included, exactly as ``pending`` was: waiting on
#: the customer has never paused the clock (see docs/architecture/sla.md).
_OPEN_STATUSES = tuple(ACTIVE | AWAITING_OTHERS)


class _EffectivePolicy:
    """Normalizes "queue has an SlaPolicy" vs. "queue only has its own
    legacy flat fields" into one shape the check/escalation logic reads
    uniformly, so nothing downstream needs an `if policy else queue`
    branch."""

    __slots__ = (
        "first_response_target_minutes",
        "resolution_target_minutes",
        "warning_threshold_percent",
        "business_hours_aware",
        "escalation_rules",
    )

    def __init__(self, queue: Queue, policy: SlaPolicy | None) -> None:
        if policy is not None and policy.is_active:
            self.first_response_target_minutes = policy.first_response_target_minutes
            self.resolution_target_minutes = policy.resolution_target_minutes
            self.warning_threshold_percent: int | None = policy.warning_threshold_percent
            self.business_hours_aware = policy.business_hours_aware
            self.escalation_rules = policy.escalation_rules
        else:
            self.first_response_target_minutes = queue.first_response_target_minutes
            self.resolution_target_minutes = queue.resolution_target_minutes
            # No warning concept for the legacy fallback — preserves
            # exactly the pre-SLA-Builder behavior (breach-only) for any
            # queue that hasn't adopted a policy.
            self.warning_threshold_percent = None
            self.business_hours_aware = False
            self.escalation_rules = []


class SlaMonitorService:
    def __init__(
        self,
        *,
        events: DomainEventPublisher,
        conversations: ConversationService,
        notifications: NotificationService,
    ) -> None:
        self._events = events
        self._conversations = conversations
        self._notifications = notifications

    async def check_breaches(self, session: AsyncSession) -> int:
        now = datetime.now(UTC)
        result = await session.execute(
            select(Conversation, Queue, SlaPolicy)
            .join(Queue, Conversation.queue_id == Queue.id)
            .outerjoin(SlaPolicy, Queue.sla_policy_id == SlaPolicy.id)
            .where(
                Conversation.deleted_at.is_(None),
                Conversation.status.in_(_OPEN_STATUSES),
            )
        )
        schedule_cache: dict[UUID, BusinessHoursSchedule] = {}
        breached = 0
        for conversation, queue, policy in result.all():
            effective = _EffectivePolicy(queue, policy)
            if await self._check_first_response(
                conversation, effective, now=now, session=session, schedule_cache=schedule_cache
            ):
                breached += 1
            if await self._check_resolution(
                conversation, effective, now=now, session=session, schedule_cache=schedule_cache
            ):
                breached += 1
        return breached

    async def _resolve_deadline(
        self,
        conversation: Conversation,
        effective: _EffectivePolicy,
        *,
        target_minutes: int,
        session: AsyncSession,
        schedule_cache: dict[UUID, BusinessHoursSchedule],
    ) -> datetime:
        if not effective.business_hours_aware:
            return conversation.created_at + timedelta(minutes=target_minutes)
        schedule = await self._get_schedule(session, conversation.company_id, schedule_cache)
        return add_business_minutes(conversation.created_at, target_minutes, schedule)

    async def _get_schedule(
        self,
        session: AsyncSession,
        company_id: UUID,
        cache: dict[UUID, BusinessHoursSchedule],
    ) -> BusinessHoursSchedule:
        if company_id in cache:
            return cache[company_id]
        company = await session.get(Company, company_id)
        settings = company.settings if company is not None else {}
        holidays = (
            (await session.execute(select(Holiday).where(Holiday.company_id == company_id)))
            .scalars()
            .all()
        )
        fixed_dates: list[date] = [h.date for h in holidays if not h.recurs_annually]
        recurring: list[tuple[int, int]] = [
            (h.date.month, h.date.day) for h in holidays if h.recurs_annually
        ]
        schedule = resolve_schedule(
            settings, holiday_dates=fixed_dates, recurring_holidays=recurring
        )
        cache[company_id] = schedule
        return schedule

    async def _check_first_response(
        self,
        conversation: Conversation,
        effective: _EffectivePolicy,
        *,
        now: datetime,
        session: AsyncSession,
        schedule_cache: dict[UUID, BusinessHoursSchedule],
    ) -> bool:
        target = effective.first_response_target_minutes
        if (
            target is None
            or conversation.first_response_at is not None
            or conversation.sla_first_response_breached_at is not None
        ):
            return False

        deadline = await self._resolve_deadline(
            conversation,
            effective,
            target_minutes=target,
            session=session,
            schedule_cache=schedule_cache,
        )
        if now >= deadline:
            conversation.sla_first_response_breached_at = now
            await self._publish(
                "conversation.sla_breached", conversation, breach_type="first_response"
            )
            await self._run_escalations(
                conversation,
                effective,
                trigger="breach",
                breach_type="first_response",
                session=session,
            )
            return True

        already_warned = conversation.sla_first_response_warned_at is not None
        if effective.warning_threshold_percent is not None and not already_warned:
            await self._maybe_warn(
                conversation,
                effective,
                target_minutes=target,
                breach_type="first_response",
                warned_at_attr="sla_first_response_warned_at",
                now=now,
                session=session,
                schedule_cache=schedule_cache,
            )
        return False

    async def _check_resolution(
        self,
        conversation: Conversation,
        effective: _EffectivePolicy,
        *,
        now: datetime,
        session: AsyncSession,
        schedule_cache: dict[UUID, BusinessHoursSchedule],
    ) -> bool:
        target = effective.resolution_target_minutes
        if target is None or conversation.sla_resolution_breached_at is not None:
            return False

        deadline = await self._resolve_deadline(
            conversation,
            effective,
            target_minutes=target,
            session=session,
            schedule_cache=schedule_cache,
        )
        if now >= deadline:
            conversation.sla_resolution_breached_at = now
            await self._publish("conversation.sla_breached", conversation, breach_type="resolution")
            await self._run_escalations(
                conversation,
                effective,
                trigger="breach",
                breach_type="resolution",
                session=session,
            )
            return True

        already_warned = conversation.sla_resolution_warned_at is not None
        if effective.warning_threshold_percent is not None and not already_warned:
            await self._maybe_warn(
                conversation,
                effective,
                target_minutes=target,
                breach_type="resolution",
                warned_at_attr="sla_resolution_warned_at",
                now=now,
                session=session,
                schedule_cache=schedule_cache,
            )
        return False

    async def _maybe_warn(
        self,
        conversation: Conversation,
        effective: _EffectivePolicy,
        *,
        target_minutes: int,
        breach_type: str,
        warned_at_attr: str,
        now: datetime,
        session: AsyncSession,
        schedule_cache: dict[UUID, BusinessHoursSchedule],
    ) -> None:
        assert effective.warning_threshold_percent is not None
        warning_minutes = target_minutes * effective.warning_threshold_percent // 100
        warning_deadline = await self._resolve_deadline(
            conversation,
            effective,
            target_minutes=warning_minutes,
            session=session,
            schedule_cache=schedule_cache,
        )
        if now < warning_deadline:
            return
        setattr(conversation, warned_at_attr, now)
        await self._publish(
            "conversation.sla_warning",
            conversation,
            breach_type=breach_type,
            extra={"warning_threshold_percent": effective.warning_threshold_percent},
        )
        await self._run_escalations(
            conversation, effective, trigger="warning", breach_type=breach_type, session=session
        )

    async def _publish(
        self,
        event_type: str,
        conversation: Conversation,
        *,
        breach_type: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "breach_type": breach_type,
            "queue_id": str(conversation.queue_id) if conversation.queue_id else None,
            "conversation_id": str(conversation.id),
        }
        if extra:
            payload.update(extra)
        await self._events.publish(
            DomainEvent(
                event_type=event_type,
                company_id=conversation.company_id,
                aggregate_type="conversation",
                aggregate_id=conversation.id,
                payload=payload,
            )
        )

    async def _run_escalations(
        self,
        conversation: Conversation,
        effective: _EffectivePolicy,
        *,
        trigger: str,
        breach_type: str,
        session: AsyncSession,
    ) -> None:
        for rule in effective.escalation_rules:
            if rule.get("trigger") != trigger:
                continue
            try:
                await self._run_one_escalation(
                    conversation, rule, trigger=trigger, breach_type=breach_type
                )
            except Exception:
                # A malformed/stale rule (e.g. pointing at a deleted
                # agent) must not abort the sweep for every other
                # conversation — logged and skipped, same reasoning as
                # WorkflowEngine's per-step failure handling.
                logger.warning(
                    "sla_escalation_failed",
                    conversation_id=str(conversation.id),
                    rule=rule,
                    exc_info=True,
                )

    async def _run_one_escalation(
        self,
        conversation: Conversation,
        rule: dict[str, Any],
        *,
        trigger: str,
        breach_type: str,
    ) -> None:
        action = rule.get("action")
        if action == "reassign_queue":
            await self._conversations.update(
                company_id=conversation.company_id,
                conversation_id=conversation.id,
                status=None,
                assigned_agent_id=None,
                queue_id=UUID(rule["target_queue_id"]),
                # Not a supervisor handing it over — a target the company
                # missed. The timeline has to say which, or "why did this
                # move at 02:00" has no answer.
                ownership_reason=OwnershipReason.ESCALATION,
            )
        elif action == "reassign_agent":
            await self._conversations.update(
                company_id=conversation.company_id,
                conversation_id=conversation.id,
                status=None,
                assigned_agent_id=UUID(rule["target_agent_id"]),
                ownership_reason=OwnershipReason.ESCALATION,
            )
        elif action == "notify":
            for raw_user_id in rule.get("user_ids", []):
                await self._notifications.create(
                    company_id=conversation.company_id,
                    user_id=UUID(raw_user_id),
                    notification_type="sla_escalation",
                    title=f"SLA {breach_type.replace('_', ' ')} needs attention",
                    body=(
                        f"A conversation has "
                        f"{'breached' if trigger == 'breach' else 'is approaching'} its "
                        f"{breach_type.replace('_', ' ')} SLA target."
                    ),
                    payload={"conversation_id": str(conversation.id)},
                )
