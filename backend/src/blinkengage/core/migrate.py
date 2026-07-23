"""Serializes ``alembic upgrade head`` across concurrently-starting containers.

``backend``, ``celery-worker``, and ``celery-beat`` all run this on startup
so the schema is guaranteed ready regardless of which one starts first —
but without coordination, two containers starting at the same moment can
both issue the same ``CREATE TABLE`` and one fails with a duplicate-object
error. A Postgres advisory lock serializes them: whoever gets the lock runs
the migration; everyone else blocks until it's released, then finds the
schema already at head and no-ops. This also protects a future multi-replica
rollout of the same service, not just cross-service races.
"""

import asyncio
import subprocess
import sys

import asyncpg

from blinkengage.core.config import get_settings

# Arbitrary fixed constant identifying this application's migration lock.
_ADVISORY_LOCK_KEY = 875_193_001


async def run_migrations_with_lock() -> int:
    settings = get_settings()
    url = settings.database_url.replace("postgresql+asyncpg", "postgresql")
    conn = await asyncpg.connect(url)
    try:
        await conn.execute("SELECT pg_advisory_lock($1)", _ADVISORY_LOCK_KEY)
        result = subprocess.run(["alembic", "upgrade", "head"], check=False)
        return result.returncode
    finally:
        await conn.execute("SELECT pg_advisory_unlock($1)", _ADVISORY_LOCK_KEY)
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run_migrations_with_lock()))
