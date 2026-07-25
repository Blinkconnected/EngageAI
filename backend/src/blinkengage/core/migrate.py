"""Serializes ``alembic upgrade head`` (and the RBAC permission sync right
after it) across concurrently-starting containers.

``backend``, ``celery-worker``, and ``celery-beat`` all run this on startup
so the schema is guaranteed ready regardless of which one starts first —
but without coordination, two containers starting at the same moment can
both issue the same ``CREATE TABLE`` and one fails with a duplicate-object
error. A Postgres advisory lock serializes them: whoever gets the lock runs
the migration; everyone else blocks until it's released, then finds the
schema already at head and no-ops. This also protects a future multi-replica
rollout of the same service, not just cross-service races.

Right after the migration, still under the same lock, every company's RBAC
permission grants are reconciled against ``domain.rbac.py``'s current
definitions (see ``infrastructure.database.permission_sync``) — meaning a
developer who adds a new permission (or extends an existing role's default
set) needs no bespoke backfill migration at all: the very next deploy's
startup picks it up automatically, for every company, not just new ones.
"""

import asyncio
import subprocess
import sys

import asyncpg

from blinkengage.application.services.permission_sync_service import PermissionSyncService
from blinkengage.core.config import Settings, get_settings
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)

# Arbitrary fixed constant identifying this application's migration lock.
_ADVISORY_LOCK_KEY = 875_193_001
_LOCK_POLL_INTERVAL_SECONDS = 0.5


async def acquire_advisory_lock(conn: asyncpg.Connection) -> None:
    """Blocks until this process holds the cross-container migration
    lock — via polling ``pg_try_advisory_lock`` (non-blocking), never a
    single blocking ``pg_advisory_lock`` call.

    That distinction matters, confirmed live: a blocking
    ``pg_advisory_lock`` leaves the waiting connection's implicit
    single-statement transaction open for the *entire* wait. Any
    migration that also runs a ``CREATE INDEX CONCURRENTLY`` (which must
    wait for every other transaction in the database — not just ones
    touching its own table — to finish before it can complete) then
    deadlocks outright the moment more than one container starts at
    once: the index build can't finish until the waiters' transactions
    end, and the waiters can't end theirs until the lock holder finishes
    (which is waiting on them). Polling means a waiting connection is
    genuinely idle — no open transaction — between attempts, so it never
    holds back a concurrent index build happening elsewhere.
    """
    while not await conn.fetchval("SELECT pg_try_advisory_lock($1)", _ADVISORY_LOCK_KEY):
        await asyncio.sleep(_LOCK_POLL_INTERVAL_SECONDS)


async def release_advisory_lock(conn: asyncpg.Connection) -> None:
    await conn.execute("SELECT pg_advisory_unlock($1)", _ADVISORY_LOCK_KEY)


async def run_migrations_with_lock() -> int:
    settings = get_settings()
    url = settings.database_url.replace("postgresql+asyncpg", "postgresql")
    conn = await asyncpg.connect(url)
    try:
        await acquire_advisory_lock(conn)
        result = subprocess.run(["alembic", "upgrade", "head"], check=False)
        if result.returncode != 0:
            return result.returncode
        await _sync_permissions(settings)
        return 0
    finally:
        await release_advisory_lock(conn)
        await conn.close()


async def _sync_permissions(settings: Settings) -> None:
    engine = create_engine(settings)
    try:
        session_factory = create_session_factory(engine)
        async with session_scope(session_factory) as session:
            result = await PermissionSyncService(session).sync()
        if result.changed:
            print(
                f"[migrate] permission sync: seeded {result.permissions_seeded} permission(s), "
                f"created {result.roles_created} role(s), granted {result.grants_added} "
                "permission grant(s)",
                file=sys.stderr,
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(run_migrations_with_lock()))
