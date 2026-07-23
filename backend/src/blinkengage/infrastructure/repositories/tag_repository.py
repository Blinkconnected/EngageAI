from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.customer import Tag


class TagRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_name(self, *, company_id: UUID, name: str) -> Tag | None:
        result = await self._session.execute(
            select(Tag).where(Tag.company_id == company_id, Tag.name == name)
        )
        return result.scalar_one_or_none()

    async def add(self, tag: Tag) -> Tag:
        self._session.add(tag)
        await self._session.flush()
        return tag

    async def get_or_create(self, *, company_id: UUID, name: str) -> Tag:
        existing = await self.get_by_name(company_id=company_id, name=name)
        if existing is not None:
            return existing
        return await self.add(Tag(company_id=company_id, name=name))
