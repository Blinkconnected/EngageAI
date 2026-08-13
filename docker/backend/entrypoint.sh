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
python -m blinkengage.core.migrate

# Once, here, before uvicorn spawns anything. The multiprocess sample
# files are named by pid and pids are recycled, so a file that outlives
# the process that wrote it is read as a live worker: counters come back
# from the previous run and any rate spanning the restart is invented. A
# worker cannot do this itself — whichever started last would delete its
# siblings' files.
#
# On the default /dev/shm path Docker already recreates the tmpfs on
# restart, so this is usually a no-op. It is what makes the guarantee hold
# if PROMETHEUS_MULTIPROC_DIR is repointed somewhere persistent. Also a
# no-op when the variable is unset, which is the dev image and the tests.
echo "[entrypoint] preparing metrics directory..."
python -m blinkengage.core.metrics_exposition

echo "[entrypoint] starting application..."
exec "$@"
