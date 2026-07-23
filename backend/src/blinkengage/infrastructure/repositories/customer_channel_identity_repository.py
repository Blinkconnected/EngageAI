from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.customer_channel_identity import (
    CustomerChannelIdentity,
)


class CustomerChannelIdentityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_customer_id(
        self, *, company_id: UUID, channel_type: str, external_id: str
    ) -> UUID | None:
        result = await self._session.execute(
            select(CustomerChannelIdentity.customer_id).where(
                CustomerChannelIdentity.company_id == company_id,
                CustomerChannelIdentity.channel_type == channel_type,
                CustomerChannelIdentity.external_id == external_id,
            )
        )
        return result.scalar_one_or_none()

    async def link(
        self, *, company_id: UUID, customer_id: UUID, channel_type: str, external_id: str
    ) -> CustomerChannelIdentity:
        identity = CustomerChannelIdentity(
            company_id=company_id,
            customer_id=customer_id,
            channel_type=channel_type,
            external_id=external_id,
        )
        self._session.add(identity)
        await self._session.flush()
        return identity
