#!/usr/bin/env bash
set -euo pipefail

echo "[entrypoint] waiting for database..."
python - <<'PY'
import asyncio
import os
import sys

import asyncpg


async def wait_for_database() -> None:
    url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg", "postgresql")
    for attempt in range(1, 31):
        try:
            conn = await asyncpg.connect(url)
            await conn.close()
            return
        except Exception as exc:  # noqa: BLE001 - best-effort readiness probe
            print(f"[entrypoint] database not ready ({exc}); attempt {attempt}/30", file=sys.stderr)
            await asyncio.sleep(2)
    print("[entrypoint] database did not become ready in time", file=sys.stderr)
    sys.exit(1)


asyncio.run(wait_for_database())
PY

echo "[entrypoint] running database migrations..."
alembic upgrade head

echo "[entrypoint] starting application..."
exec "$@"
