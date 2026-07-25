"""Standalone entry point for the RBAC permission sync — for an operator
to run on demand (e.g. right after deploying code that added a
permission, without waiting for the next container restart/migration).

Usage (inside the backend container or with ``DATABASE_URL`` pointed at
the real database):

    python -m blinkengage.core.sync_permissions

Safe to run at any time, including while the application is live and
serving traffic, and safe to run more than once — see
``infrastructure.database.permission_sync`` for the idempotency
guarantee. Takes the same cross-process advisory lock
``core.migrate`` uses, so it can't race a container's own startup sync.
"""

import asyncio
import sys

import asyncpg

from blinkengage.application.services.permission_sync_service import PermissionSyncService
from blinkengage.core.config import get_settings
from blinkengage.core.migrate import _ADVISORY_LOCK_KEY
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)


async def main() -> int:
    settings = get_settings()
    lock_url = settings.database_url.replace("postgresql+asyncpg", "postgresql")
    lock_conn = await asyncpg.connect(lock_url)
    try:
        await lock_conn.execute("SELECT pg_advisory_lock($1)", _ADVISORY_LOCK_KEY)
        engine = create_engine(settings)
        try:
            session_factory = create_session_factory(engine)
            async with session_scope(session_factory) as session:
                result = await PermissionSyncService(session).sync()
        finally:
            await engine.dispose()
    finally:
        await lock_conn.execute("SELECT pg_advisory_unlock($1)", _ADVISORY_LOCK_KEY)
        await lock_conn.close()

    print(
        f"Permission sync complete: seeded {result.permissions_seeded} permission(s), "
        f"created {result.roles_created} role(s), granted {result.grants_added} "
        "permission grant(s) across all companies.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
