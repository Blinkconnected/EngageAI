from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.erp import ErpConfig


class ErpConfigRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, *, company_id: UUID, erp_config_id: UUID) -> ErpConfig | None:
        result = await self._session.execute(
            select(ErpConfig).where(
                ErpConfig.id == erp_config_id,
                ErpConfig.company_id == company_id,
                ErpConfig.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id_any_company(self, erp_config_id: UUID) -> ErpConfig | None:
        """Unscoped by ``company_id`` — the inbound ERPNext webhook carries
        no JWT/tenant context, only the config id in the URL. Security here
        is the shared webhook secret, not tenant isolation (mirrors
        ``ChannelConfigRepository.get_by_id_any_company``)."""
        result = await self._session.execute(
            select(ErpConfig).where(ErpConfig.id == erp_config_id, ErpConfig.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_active_for_company(self, *, company_id: UUID) -> ErpConfig | None:
        """One active ERPNext connection per company is all this
        integration supports — used by the outbound sync consumer to
        decide whether a company has ERP configured at all."""
        result = await self._session.execute(
            select(ErpConfig).where(
                ErpConfig.company_id == company_id,
                ErpConfig.is_active.is_(True),
                ErpConfig.deleted_at.is_(None),
            )
        )
        return result.scalars().first()

    async def list_for_company(
        self, *, company_id: UUID, offset: int, limit: int
    ) -> tuple[list[ErpConfig], int]:
        base = select(ErpConfig).where(
            ErpConfig.company_id == company_id, ErpConfig.deleted_at.is_(None)
        )
        total = (
            await self._session.execute(
                select(func.count()).select_from(base.with_only_columns(ErpConfig.id).subquery())
            )
        ).scalar_one()
        result = await self._session.execute(
            base.order_by(ErpConfig.created_at).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), total

    async def add(self, erp_config: ErpConfig) -> ErpConfig:
        self._session.add(erp_config)
        await self._session.flush()
        return erp_config

    async def soft_delete(self, erp_config: ErpConfig) -> None:
        erp_config.deleted_at = datetime.now(UTC)
        await self._session.flush()
