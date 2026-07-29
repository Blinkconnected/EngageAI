"""Platform (super) administration — operating the installation itself.

Everything here acts *across* tenants, which is the one place in this
codebase that deliberately steps outside the "one JWT, one company_id,
every query filtered" isolation model. That is why it is a separate
service, a separate API prefix, and a separate principal type
(``PlatformContext``) rather than an extra permission on the tenant
catalog: the blast radius stays visible in one file.

Scope is deliberately narrow — **company lifecycle and, later, billing;
never tenant content**. There is no method here that reads a
conversation, a message or a customer, and none should be added: the
product promise is that platform staff cannot read customers'
conversations. Aggregate counts are fine; rows are not.
"""

from uuid import UUID

from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.exceptions import EntityNotFoundError
from blinkengage.infrastructure.database.models.company import Company, CompanyStatus
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.platform_repository import (
    CompanyOverview,
    PlatformRepository,
)


class PlatformService:
    def __init__(
        self,
        *,
        companies: CompanyRepository,
        platform: PlatformRepository,
        events: DomainEventPublisher,
    ) -> None:
        self._companies = companies
        self._platform = platform
        self._events = events

    async def list_companies(
        self,
        *,
        offset: int,
        limit: int,
        search: str | None = None,
        status: CompanyStatus | None = None,
    ) -> tuple[list[CompanyOverview], int]:
        return await self._platform.list_company_overviews(
            offset=offset, limit=limit, search=search, status=status
        )

    async def get_company(self, *, company_id: UUID) -> CompanyOverview:
        overview = await self._platform.get_company_overview(company_id=company_id)
        if overview is None:
            raise EntityNotFoundError("Company", company_id)
        return overview

    async def set_status(
        self, *, company_id: UUID, status: CompanyStatus, actor_user_id: UUID, reason: str | None
    ) -> Company:
        """Suspends, reactivates or trials a company.

        Suspension is enforced at sign-in, at token refresh and on every
        authenticated request (see ``AuthService._assert_company_usable``
        and ``deps.get_current_user``) — but deliberately **not** at
        message ingress: a suspended company keeps receiving its
        customers' messages, so nothing is lost while a billing dispute
        is resolved and the tenant is not silently dropping their own
        customers on the floor.

        Publishes a domain event, which the audit-log consumer records —
        a platform operator changing a customer's account state is
        exactly the sort of action that must be reconstructable later.
        """
        company = await self._companies.get_by_id(company_id)
        if company is None or company.deleted_at is not None:
            raise EntityNotFoundError("Company", company_id)

        previous = company.status
        company.status = status
        await self._events.publish(
            DomainEvent(
                event_type="platform.company_status_changed",
                company_id=company.id,
                aggregate_type="company",
                aggregate_id=company.id,
                actor_user_id=actor_user_id,
                payload={
                    "previous_status": previous.value,
                    "status": status.value,
                    "reason": reason,
                },
            )
        )
        return company
