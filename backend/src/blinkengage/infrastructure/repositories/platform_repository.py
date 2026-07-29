"""Cross-tenant reads for the platform administration API.

Every other repository in this codebase pins ``company_id`` in its
WHERE clause; this one deliberately does not, which is exactly why it
lives in its own file with its own name. Anything unscoped is here and
nowhere else, so a reviewer auditing tenant isolation has one file to
read rather than a convention to spot-check across a hundred methods.

Only counts and company metadata are exposed — never tenant rows. A
method that returns conversations, messages or customers does not belong
here (see ``PlatformService``'s module docstring).
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.agent import Agent
from blinkengage.infrastructure.database.models.billing import (
    BillingPlan,
    Subscription,
    SubscriptionStatus,
)
from blinkengage.infrastructure.database.models.company import Company, CompanyStatus
from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.database.models.user import User


@dataclass(frozen=True, slots=True)
class CompanyOverview:
    """A company as the platform operator sees it: identity, lifecycle
    state, and size — never its content. Defined here alongside the
    query that builds it, the same way ``ReportingRepository`` owns its
    own row dataclasses."""

    company: Company
    user_count: int
    agent_count: int
    conversation_count: int
    # Billing state, so the console's companies grid can answer "who is
    # actually paying?" without a request per row. Both None for a
    # company that has never subscribed.
    plan_name: str | None = None
    subscription_status: SubscriptionStatus | None = None


class PlatformRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _counts_for(self, company_ids: list[UUID]) -> dict[UUID, tuple[int, int, int]]:
        """One grouped query per entity for the whole page, not three per
        company — the same batch-aggregate shape
        ``MessageRepository.unread_counts_for_conversations`` uses. A
        company absent from a result simply has zero of that thing."""
        if not company_ids:
            return {}

        async def _count(model: type[User] | type[Agent] | type[Conversation]) -> dict[UUID, int]:
            result = await self._session.execute(
                select(model.company_id, func.count())
                .where(model.company_id.in_(company_ids), model.deleted_at.is_(None))
                .group_by(model.company_id)
            )
            return {row[0]: row[1] for row in result.all()}

        users = await _count(User)
        agents = await _count(Agent)
        conversations = await _count(Conversation)
        return {
            company_id: (
                users.get(company_id, 0),
                agents.get(company_id, 0),
                conversations.get(company_id, 0),
            )
            for company_id in company_ids
        }

    async def _subscriptions_for(
        self, company_ids: list[UUID]
    ) -> dict[UUID, tuple[str, SubscriptionStatus]]:
        """The live subscription per company, in one query for the whole
        page — same batch-aggregate shape as ``_counts_for`` above.

        This reads billing metadata only (plan name and lifecycle state).
        It is the one join in this file that touches a per-company table
        rather than a count, and it stays inside the promise: a plan name
        is the platform's own catalog entry, not the tenant's content.
        """
        if not company_ids:
            return {}
        result = await self._session.execute(
            select(Subscription.company_id, BillingPlan.name, Subscription.status)
            .join(BillingPlan, BillingPlan.id == Subscription.plan_id)
            .where(
                Subscription.company_id.in_(company_ids),
                Subscription.status.not_in(
                    [SubscriptionStatus.CANCELLED, SubscriptionStatus.EXPIRED]
                ),
            )
            .order_by(Subscription.created_at.desc())
        )
        current: dict[UUID, tuple[str, SubscriptionStatus]] = {}
        for company_id, plan_name, status_value in result.all():
            current.setdefault(company_id, (plan_name, status_value))
        return current

    async def list_company_overviews(
        self,
        *,
        offset: int,
        limit: int,
        search: str | None = None,
        status: CompanyStatus | None = None,
    ) -> tuple[list[CompanyOverview], int]:
        base = select(Company).where(Company.deleted_at.is_(None))
        if search:
            pattern = f"%{search}%"
            base = base.where(or_(Company.name.ilike(pattern), Company.slug.ilike(pattern)))
        if status is not None:
            base = base.where(Company.status == status)

        total = (
            await self._session.execute(
                select(func.count()).select_from(base.with_only_columns(Company.id).subquery())
            )
        ).scalar_one()
        result = await self._session.execute(
            base.order_by(Company.created_at.desc()).offset(offset).limit(limit)
        )
        companies = list(result.scalars().all())
        company_ids = [company.id for company in companies]
        counts = await self._counts_for(company_ids)
        subscriptions = await self._subscriptions_for(company_ids)
        return (
            [
                CompanyOverview(
                    company=company,
                    user_count=counts.get(company.id, (0, 0, 0))[0],
                    agent_count=counts.get(company.id, (0, 0, 0))[1],
                    conversation_count=counts.get(company.id, (0, 0, 0))[2],
                    plan_name=subscriptions.get(company.id, (None, None))[0],
                    subscription_status=subscriptions.get(company.id, (None, None))[1],
                )
                for company in companies
            ],
            total,
        )

    async def get_company_overview(self, *, company_id: UUID) -> CompanyOverview | None:
        result = await self._session.execute(
            select(Company).where(Company.id == company_id, Company.deleted_at.is_(None))
        )
        company = result.scalar_one_or_none()
        if company is None:
            return None
        users, agents, conversations = (await self._counts_for([company.id])).get(
            company.id, (0, 0, 0)
        )
        plan_name, subscription_status = (await self._subscriptions_for([company.id])).get(
            company.id, (None, None)
        )
        return CompanyOverview(
            company=company,
            user_count=users,
            agent_count=agents,
            conversation_count=conversations,
            plan_name=plan_name,
            subscription_status=subscription_status,
        )
