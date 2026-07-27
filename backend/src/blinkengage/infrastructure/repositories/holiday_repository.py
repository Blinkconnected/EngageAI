from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.sla import Holiday


class HolidayRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, *, company_id: UUID, holiday_id: UUID) -> Holiday | None:
        result = await self._session.execute(
            select(Holiday).where(Holiday.id == holiday_id, Holiday.company_id == company_id)
        )
        return result.scalar_one_or_none()

    async def get_by_date(self, *, company_id: UUID, on_date: date) -> Holiday | None:
        result = await self._session.execute(
            select(Holiday).where(Holiday.company_id == company_id, Holiday.date == on_date)
        )
        return result.scalar_one_or_none()

    async def list_for_company(self, company_id: UUID) -> list[Holiday]:
        result = await self._session.execute(
            select(Holiday).where(Holiday.company_id == company_id).order_by(Holiday.date)
        )
        return list(result.scalars().all())

    async def add(self, holiday: Holiday) -> Holiday:
        self._session.add(holiday)
        await self._session.flush()
        return holiday

    async def delete(self, holiday: Holiday) -> None:
        await self._session.delete(holiday)
        await self._session.flush()
