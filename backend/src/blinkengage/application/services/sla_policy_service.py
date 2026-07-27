"""SLA Builder CRUD: policies, holidays, and a preview calculator. See
``docs/architecture/sla.md``. Queue assignment itself (``Queue.
sla_policy_id``) is edited via ``QueueService``, not here — a policy is
assigned *to* a queue, not the other way around.
"""

from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from blinkengage.domain.business_hours import add_business_minutes, resolve_schedule
from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.exceptions import (
    EntityAlreadyExistsError,
    EntityNotFoundError,
    SlaPolicyHasAssignedQueuesError,
)
from blinkengage.infrastructure.database.models.sla import Holiday, SlaPolicy
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.holiday_repository import HolidayRepository
from blinkengage.infrastructure.repositories.sla_policy_repository import SlaPolicyRepository


class SlaPolicyService:
    def __init__(
        self,
        *,
        policies: SlaPolicyRepository,
        holidays: HolidayRepository,
        companies: CompanyRepository,
        events: DomainEventPublisher,
    ) -> None:
        self._policies = policies
        self._holidays = holidays
        self._companies = companies
        self._events = events

    # --- Policies ---

    async def get(self, *, company_id: UUID, policy_id: UUID) -> SlaPolicy:
        policy = await self._policies.get_by_id(company_id=company_id, policy_id=policy_id)
        if policy is None:
            raise EntityNotFoundError("SlaPolicy", policy_id)
        return policy

    async def list_policies(self, company_id: UUID) -> list[SlaPolicy]:
        return await self._policies.list_for_company(company_id)

    async def assigned_queue_count(self, policy_id: UUID) -> int:
        return await self._policies.assigned_queue_count(policy_id)

    async def create(
        self,
        *,
        company_id: UUID,
        name: str,
        description: str | None,
        first_response_target_minutes: int | None,
        resolution_target_minutes: int | None,
        warning_threshold_percent: int,
        business_hours_aware: bool,
        escalation_rules: list[dict[str, Any]],
        actor_user_id: UUID | None = None,
    ) -> SlaPolicy:
        if await self._policies.get_by_name(company_id=company_id, name=name) is not None:
            raise EntityAlreadyExistsError("SlaPolicy", "name", name)
        policy = await self._policies.add(
            SlaPolicy(
                company_id=company_id,
                name=name,
                description=description,
                first_response_target_minutes=first_response_target_minutes,
                resolution_target_minutes=resolution_target_minutes,
                warning_threshold_percent=warning_threshold_percent,
                business_hours_aware=business_hours_aware,
                escalation_rules=escalation_rules,
            )
        )
        await self._events.publish(
            DomainEvent(
                event_type="sla_policy.created",
                company_id=company_id,
                aggregate_type="sla_policy",
                aggregate_id=policy.id,
                actor_user_id=actor_user_id,
                payload={"name": policy.name},
            )
        )
        return policy

    async def update(
        self,
        *,
        company_id: UUID,
        policy_id: UUID,
        name: str | None,
        description: str | None,
        first_response_target_minutes: int | None,
        resolution_target_minutes: int | None,
        warning_threshold_percent: int | None,
        business_hours_aware: bool | None,
        escalation_rules: list[dict[str, Any]] | None,
        is_active: bool | None,
        actor_user_id: UUID | None = None,
    ) -> SlaPolicy:
        policy = await self.get(company_id=company_id, policy_id=policy_id)
        if name is not None and name != policy.name:
            if await self._policies.get_by_name(company_id=company_id, name=name) is not None:
                raise EntityAlreadyExistsError("SlaPolicy", "name", name)
            policy.name = name
        if description is not None:
            policy.description = description
        if first_response_target_minutes is not None:
            policy.first_response_target_minutes = first_response_target_minutes
        if resolution_target_minutes is not None:
            policy.resolution_target_minutes = resolution_target_minutes
        if warning_threshold_percent is not None:
            policy.warning_threshold_percent = warning_threshold_percent
        if business_hours_aware is not None:
            policy.business_hours_aware = business_hours_aware
        if escalation_rules is not None:
            policy.escalation_rules = escalation_rules
        if is_active is not None:
            policy.is_active = is_active

        await self._events.publish(
            DomainEvent(
                event_type="sla_policy.updated",
                company_id=company_id,
                aggregate_type="sla_policy",
                aggregate_id=policy.id,
                actor_user_id=actor_user_id,
                payload={"name": policy.name, "is_active": policy.is_active},
            )
        )
        return policy

    async def delete(
        self, *, company_id: UUID, policy_id: UUID, actor_user_id: UUID | None = None
    ) -> None:
        policy = await self.get(company_id=company_id, policy_id=policy_id)
        queue_count = await self._policies.assigned_queue_count(policy_id)
        if queue_count > 0:
            raise SlaPolicyHasAssignedQueuesError(policy.name, queue_count)
        await self._policies.delete(policy)
        await self._events.publish(
            DomainEvent(
                event_type="sla_policy.deleted",
                company_id=company_id,
                aggregate_type="sla_policy",
                aggregate_id=policy_id,
                actor_user_id=actor_user_id,
                payload={"name": policy.name},
            )
        )

    # --- Holidays ---

    async def get_holiday(self, *, company_id: UUID, holiday_id: UUID) -> Holiday:
        holiday = await self._holidays.get_by_id(company_id=company_id, holiday_id=holiday_id)
        if holiday is None:
            raise EntityNotFoundError("Holiday", holiday_id)
        return holiday

    async def list_holidays(self, company_id: UUID) -> list[Holiday]:
        return await self._holidays.list_for_company(company_id)

    async def create_holiday(
        self,
        *,
        company_id: UUID,
        name: str,
        on_date: date,
        recurs_annually: bool,
        actor_user_id: UUID | None = None,
    ) -> Holiday:
        if await self._holidays.get_by_date(company_id=company_id, on_date=on_date) is not None:
            raise EntityAlreadyExistsError("Holiday", "date", on_date.isoformat())
        holiday = await self._holidays.add(
            Holiday(company_id=company_id, name=name, date=on_date, recurs_annually=recurs_annually)
        )
        await self._events.publish(
            DomainEvent(
                event_type="holiday.created",
                company_id=company_id,
                aggregate_type="holiday",
                aggregate_id=holiday.id,
                actor_user_id=actor_user_id,
                payload={"name": holiday.name, "date": on_date.isoformat()},
            )
        )
        return holiday

    async def update_holiday(
        self,
        *,
        company_id: UUID,
        holiday_id: UUID,
        name: str | None,
        on_date: date | None,
        recurs_annually: bool | None,
        actor_user_id: UUID | None = None,
    ) -> Holiday:
        holiday = await self.get_holiday(company_id=company_id, holiday_id=holiday_id)
        if on_date is not None and on_date != holiday.date:
            if await self._holidays.get_by_date(company_id=company_id, on_date=on_date) is not None:
                raise EntityAlreadyExistsError("Holiday", "date", on_date.isoformat())
            holiday.date = on_date
        if name is not None:
            holiday.name = name
        if recurs_annually is not None:
            holiday.recurs_annually = recurs_annually

        await self._events.publish(
            DomainEvent(
                event_type="holiday.updated",
                company_id=company_id,
                aggregate_type="holiday",
                aggregate_id=holiday.id,
                actor_user_id=actor_user_id,
                payload={"name": holiday.name},
            )
        )
        return holiday

    async def delete_holiday(
        self, *, company_id: UUID, holiday_id: UUID, actor_user_id: UUID | None = None
    ) -> None:
        holiday = await self.get_holiday(company_id=company_id, holiday_id=holiday_id)
        await self._holidays.delete(holiday)
        await self._events.publish(
            DomainEvent(
                event_type="holiday.deleted",
                company_id=company_id,
                aggregate_type="holiday",
                aggregate_id=holiday_id,
                actor_user_id=actor_user_id,
                payload={"name": holiday.name},
            )
        )

    # --- Preview ---

    async def preview(
        self, *, company_id: UUID, policy_id: UUID, starts_at: datetime
    ) -> tuple[datetime | None, datetime | None, datetime | None, datetime | None]:
        """Returns (first_response_warning_at, first_response_deadline,
        resolution_warning_at, resolution_deadline) for a hypothetical
        conversation created at ``starts_at`` — the same math
        ``SlaMonitorService`` applies to a real one, so what an admin
        previews here is exactly what would happen in production."""
        policy = await self.get(company_id=company_id, policy_id=policy_id)
        company = await self._companies.get_by_id(company_id)
        settings = company.settings if company is not None else {}

        if policy.business_hours_aware:
            holidays = await self._holidays.list_for_company(company_id)
            fixed_dates = [h.date for h in holidays if not h.recurs_annually]
            recurring = [(h.date.month, h.date.day) for h in holidays if h.recurs_annually]
            schedule = resolve_schedule(
                settings, holiday_dates=fixed_dates, recurring_holidays=recurring
            )

            def _deadline(minutes: int) -> datetime:
                return add_business_minutes(starts_at, minutes, schedule)
        else:

            def _deadline(minutes: int) -> datetime:
                return starts_at + timedelta(minutes=minutes)

        def _target(minutes: int | None) -> datetime | None:
            return _deadline(minutes) if minutes is not None else None

        def _warning(minutes: int | None) -> datetime | None:
            if minutes is None:
                return None
            return _deadline(minutes * policy.warning_threshold_percent // 100)

        return (
            _warning(policy.first_response_target_minutes),
            _target(policy.first_response_target_minutes),
            _warning(policy.resolution_target_minutes),
            _target(policy.resolution_target_minutes),
        )
