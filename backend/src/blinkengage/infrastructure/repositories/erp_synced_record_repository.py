from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.erp import ErpSyncedRecord


class ErpSyncedRecordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_customer(
        self, *, company_id: UUID, customer_id: UUID, doctype: str | None
    ) -> list[ErpSyncedRecord]:
        conditions = [
            ErpSyncedRecord.company_id == company_id,
            ErpSyncedRecord.customer_id == customer_id,
        ]
        if doctype is not None:
            conditions.append(ErpSyncedRecord.doctype == doctype)
        result = await self._session.execute(
            select(ErpSyncedRecord)
            .where(*conditions)
            .order_by(ErpSyncedRecord.doctype, ErpSyncedRecord.external_name)
        )
        return list(result.scalars().all())

    async def upsert(
        self,
        *,
        company_id: UUID,
        customer_id: UUID | None,
        doctype: str,
        external_name: str,
        data: dict[str, Any],
        external_modified_at: datetime | None,
    ) -> ErpSyncedRecord:
        result = await self._session.execute(
            select(ErpSyncedRecord).where(
                ErpSyncedRecord.company_id == company_id,
                ErpSyncedRecord.doctype == doctype,
                ErpSyncedRecord.external_name == external_name,
            )
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            existing.data = data
            existing.external_modified_at = external_modified_at
            if customer_id is not None:
                existing.customer_id = customer_id
            await self._session.flush()
            return existing

        record = ErpSyncedRecord(
            company_id=company_id,
            customer_id=customer_id,
            doctype=doctype,
            external_name=external_name,
            data=data,
            external_modified_at=external_modified_at,
        )
        self._session.add(record)
        await self._session.flush()
        return record
