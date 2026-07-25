"""Async application-layer wrapper around
``infrastructure.database.permission_sync.sync_permissions`` — see that
module for the actual reconciliation logic and its guarantees.

Bridges the sync-``Session``-based core function into async application
code via ``AsyncSession.run_sync()``, which runs the callable against a
sync-style ``Session`` proxy bound to this same connection/transaction
(no separate transaction, no extra round-trip). Callers still own the
commit — this only flushes, matching every other service in this
codebase (the request-scoped session commits once, at the API boundary).
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.permission_sync import (
    PermissionSyncResult,
    sync_permissions,
)


class PermissionSyncService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def sync(self, *, company_id: uuid.UUID | None = None) -> PermissionSyncResult:
        return await self._session.run_sync(
            lambda sync_session: sync_permissions(sync_session, company_id=company_id)
        )
