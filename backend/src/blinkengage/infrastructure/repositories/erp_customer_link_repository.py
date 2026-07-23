from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.erp import ErpCustomerLink


class ErpCustomerLinkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_customer(self, customer_id: UUID) -> ErpCustomerLink | None:
        result = await self._session.execute(
            select(ErpCustomerLink).where(ErpCustomerLink.customer_id == customer_id)
        )
        return result.scalar_one_or_none()

    async def get_by_erp_customer_name(
        self, *, company_id: UUID, erp_customer_name: str
    ) -> ErpCustomerLink | None:
        result = await self._session.execute(
            select(ErpCustomerLink).where(
                ErpCustomerLink.company_id == company_id,
                ErpCustomerLink.erp_customer_name == erp_customer_name,
            )
        )
        return result.scalar_one_or_none()

    async def add(self, link: ErpCustomerLink) -> ErpCustomerLink:
        self._session.add(link)
        await self._session.flush()
        return link
