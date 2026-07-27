from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.customer import CustomerInternalRating


class CustomerInternalRatingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(
        self, *, company_id: UUID, rating_id: UUID
    ) -> CustomerInternalRating | None:
        result = await self._session.execute(
            select(CustomerInternalRating).where(
                CustomerInternalRating.id == rating_id,
                CustomerInternalRating.company_id == company_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_customer(
        self, *, company_id: UUID, customer_id: UUID, offset: int, limit: int
    ) -> tuple[list[CustomerInternalRating], int]:
        base = select(CustomerInternalRating).where(
            CustomerInternalRating.company_id == company_id,
            CustomerInternalRating.customer_id == customer_id,
        )
        total = (
            await self._session.execute(
                select(func.count()).select_from(
                    base.with_only_columns(CustomerInternalRating.id).subquery()
                )
            )
        ).scalar_one()
        result = await self._session.execute(
            base.order_by(CustomerInternalRating.created_at.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), total

    async def add(self, rating: CustomerInternalRating) -> CustomerInternalRating:
        self._session.add(rating)
        await self._session.flush()
        return rating

    async def delete(self, rating: CustomerInternalRating) -> None:
        await self._session.delete(rating)
        await self._session.flush()

    async def summary_for_customers(
        self, *, company_id: UUID, customer_ids: list[UUID]
    ) -> dict[UUID, tuple[float | None, int]]:
        """Average stars + count per customer, in one query — avoids an
        N+1 aggregate per row when rendering a paginated customer list.
        Customers with no ratings are simply absent from the result (the
        caller defaults to ``(None, 0)``)."""
        if not customer_ids:
            return {}
        result = await self._session.execute(
            select(
                CustomerInternalRating.customer_id,
                func.avg(CustomerInternalRating.stars),
                func.count(CustomerInternalRating.id),
            )
            .where(
                CustomerInternalRating.company_id == company_id,
                CustomerInternalRating.customer_id.in_(customer_ids),
            )
            .group_by(CustomerInternalRating.customer_id)
        )
        return {
            row[0]: (round(float(row[1]), 2) if row[1] is not None else None, row[2])
            for row in result.all()
        }

    async def summary_for_customer(
        self, *, company_id: UUID, customer_id: UUID
    ) -> tuple[float | None, int]:
        summary = await self.summary_for_customers(
            company_id=company_id, customer_ids=[customer_id]
        )
        return summary.get(customer_id, (None, 0))
