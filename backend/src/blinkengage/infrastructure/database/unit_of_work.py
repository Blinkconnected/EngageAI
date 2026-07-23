"""Concrete SQLAlchemy-backed Unit of Work."""

from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.domain.repositories.base import AbstractUnitOfWork


class SqlAlchemyUnitOfWork(AbstractUnitOfWork):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
