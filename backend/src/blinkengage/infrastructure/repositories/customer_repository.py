from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from blinkengage.infrastructure.database.models.customer import Customer, CustomerTag


class CustomerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, *, company_id: UUID, customer_id: UUID) -> Customer | None:
        result = await self._session.execute(
            select(Customer)
            .where(
                Customer.id == customer_id,
                Customer.company_id == company_id,
                Customer.deleted_at.is_(None),
            )
            .options(selectinload(Customer.customer_tags).selectinload(CustomerTag.tag))
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, *, company_id: UUID, email: str) -> Customer | None:
        result = await self._session.execute(
            select(Customer).where(
                Customer.company_id == company_id,
                Customer.email == email,
                Customer.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_for_company(
        self, *, company_id: UUID, offset: int, limit: int, search: str | None = None
    ) -> tuple[list[Customer], int]:
        base = select(Customer).where(
            Customer.company_id == company_id, Customer.deleted_at.is_(None)
        )
        if search:
            pattern = f"%{search}%"
            base = base.where(
                or_(
                    Customer.full_name.ilike(pattern),
                    Customer.email.ilike(pattern),
                    Customer.phone.ilike(pattern),
                )
            )
        total = (
            await self._session.execute(
                select(func.count()).select_from(base.with_only_columns(Customer.id).subquery())
            )
        ).scalar_one()
        result = await self._session.execute(
            base.order_by(Customer.full_name)
            .offset(offset)
            .limit(limit)
            .options(selectinload(Customer.customer_tags).selectinload(CustomerTag.tag))
        )
        return list(result.scalars().all()), total

    async def add(self, customer: Customer) -> Customer:
        self._session.add(customer)
        await self._session.flush()
        return customer

    async def soft_delete(self, customer: Customer) -> None:
        customer.deleted_at = datetime.now(UTC)
        await self._session.flush()
