from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.reporting import CsatResponse


class CsatResponseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_conversation(self, conversation_id: UUID) -> CsatResponse | None:
        result = await self._session.execute(
            select(CsatResponse).where(CsatResponse.conversation_id == conversation_id)
        )
        return result.scalar_one_or_none()

    async def add(self, response: CsatResponse) -> CsatResponse:
        self._session.add(response)
        await self._session.flush()
        return response
