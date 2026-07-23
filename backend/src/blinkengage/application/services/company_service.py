"""``CompanyService`` — company profile + admin-configurable settings.
See ``docs/architecture/administration.md``.

No ``get_current_auth``-only read gate the way Notifications (personal,
per-user) work: a company's profile/settings are shared, company-wide
information, not a personal inbox, so viewing them only requires being
an authenticated member of the company (any role), while editing
requires ``company.manage``.
"""

from typing import Any
from uuid import UUID

from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.exceptions import EntityNotFoundError
from blinkengage.infrastructure.database.models.company import Company
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository


class CompanyService:
    def __init__(self, *, companies: CompanyRepository, events: DomainEventPublisher) -> None:
        self._companies = companies
        self._events = events

    async def get(self, company_id: UUID) -> Company:
        company = await self._companies.get_by_id(company_id)
        if company is None:
            raise EntityNotFoundError("Company", company_id)
        return company

    async def update(
        self,
        *,
        company_id: UUID,
        name: str | None,
        settings: dict[str, Any] | None,
        actor_user_id: UUID | None = None,
    ) -> Company:
        company = await self.get(company_id)
        if name is not None:
            company.name = name
        if settings is not None:
            company.settings = settings
        await self._companies.save(company)
        await self._events.publish(
            DomainEvent(
                event_type="company.updated",
                company_id=company_id,
                aggregate_type="company",
                aggregate_id=company_id,
                actor_user_id=actor_user_id,
                payload={"name": company.name},
            )
        )
        return company
