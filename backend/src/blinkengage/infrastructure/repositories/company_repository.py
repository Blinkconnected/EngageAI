from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.company import Company


class CompanyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, company_id: UUID) -> Company | None:
        return await self._session.get(Company, company_id)

    async def get_by_slug(self, slug: str) -> Company | None:
        result = await self._session.execute(select(Company).where(Company.slug == slug))
        return result.scalar_one_or_none()

    async def add(self, company: Company) -> Company:
        self._session.add(company)
        await self._session.flush()
        return company
