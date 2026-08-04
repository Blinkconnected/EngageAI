"""Verifies the pgvector path against a real PostgreSQL.

The test suite runs on SQLite with the exact vector index, which is
correct and fast but cannot exercise the two things that only exist on
PostgreSQL and that fail *silently* when they are wrong:

1. **Adapter parity.** ``PgVectorIndex`` is approximate. A wrong
   ``ef_search``, a missing iterative-scan setting or a filter applied in
   the wrong order degrades recall without erroring — queries stay fast
   and answers quietly get worse. This compares its ranking against
   ``ExactVectorIndex``, which is exhaustive and therefore right by
   construction.

2. **Tenant pre-filtering under ANN.** An ANN index ranks before
   predicates apply. A "search then filter" implementation returns
   whatever fraction of its top-k happened to belong to the right tenant —
   frequently zero for a small tenant on a large installation. That reads
   as a relevance problem, not a leak, so it survives review. Here it is
   measured with a deliberately hostile corpus: one tenant holding 0.5% of
   the rows, whose nearest neighbours are all owned by somebody else.

Run against the compose stack:

    DATABASE_URL=postgresql+asyncpg://... python scripts/verify_pgvector.py
"""

import asyncio
import os
import random
import statistics
import time
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from blinkengage.infrastructure.database.models.embedding import OWNER_KNOWLEDGE_CHUNK
from blinkengage.infrastructure.database.vector import to_pgvector_literal
from blinkengage.infrastructure.vector.exact_index import ExactVectorIndex
from blinkengage.infrastructure.vector.pgvector_index import PgVectorIndex

DIMENSIONS = 1536
MODEL = "verify-pgvector"
TENANTS = 20
ROWS_PER_TENANT = 500
QUERIES = 40
TOP_K = 10


def _unit_vector(rng: random.Random) -> list[float]:
    values = [rng.gauss(0.0, 1.0) for _ in range(DIMENSIONS)]
    norm = sum(value * value for value in values) ** 0.5
    return [value / norm for value in values]


async def main() -> int:
    url = os.environ["DATABASE_URL"]
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    rng = random.Random(20260804)

    async with factory() as session:
        await session.execute(
            text("DELETE FROM embeddings WHERE model = :model"), {"model": MODEL}
        )
        # Real company ids — `embeddings.company_id` is a foreign key, and
        # inventing tenants would test an isolation boundary the database
        # is not actually enforcing here.
        tenants = list(
            (await session.execute(text("SELECT id FROM companies LIMIT :n"), {"n": TENANTS}))
            .scalars()
            .all()
        )
        await session.commit()

    if len(tenants) < 2:
        print(f"need at least 2 companies to test isolation, found {len(tenants)}")
        return 1

    # The tenant under test is one of many, holding a small fraction of
    # the corpus — the shape that breaks a filter-after-ranking
    # implementation.
    real_company = tenants[0]


    async with factory() as session:
        for tenant in tenants:
            rows = []
            for _ in range(ROWS_PER_TENANT):
                rows.append(
                    {
                        "id": str(uuid.uuid4()),
                        "company_id": str(tenant),
                        "owner_type": OWNER_KNOWLEDGE_CHUNK,
                        "owner_id": str(uuid.uuid4()),
                        "model": MODEL,
                        "dimensions": DIMENSIONS,
                        "content_hash": "0" * 64,
                        "vector": to_pgvector_literal(_unit_vector(rng)),
                    }
                )
            await session.execute(
                text(
                    "INSERT INTO embeddings (id, company_id, owner_type, owner_id, model, "
                    "dimensions, content_hash, vector) VALUES (:id, :company_id, :owner_type, "
                    ":owner_id, :model, :dimensions, :content_hash, CAST(:vector AS vector))"
                ),
                rows,
            )
        await session.commit()

    total = len(tenants) * ROWS_PER_TENANT
    print(f"seeded {total} rows across {len(tenants)} tenants; tenant under test holds {ROWS_PER_TENANT} "
          f"({ROWS_PER_TENANT / total:.2%})")

    exact_ids: list[list[uuid.UUID]] = []
    ann_ids: list[list[uuid.UUID]] = []
    latencies: list[float] = []
    foreign_rows = 0

    # **One session per query, deliberately.** `PgVectorIndex` tunes the
    # scan with `SET LOCAL`, which is scoped to a transaction — so running
    # every query inside one long-lived transaction measures something the
    # application never does. In production each request gets its own
    # request-scoped session (`api/deps.get_db_session`), and the numbers
    # differ materially: an earlier version of this script shared one
    # session across all forty queries and reported recall of 0.70 for an
    # index that is in fact exact at these parameters.
    for _ in range(QUERIES):
        query = _unit_vector(rng)

        async with factory() as session:
            exact_hits = await ExactVectorIndex(session, max_scan=total + 1).search(
                company_id=real_company,
                model=MODEL,
                query_vector=query,
                limit=TOP_K,
                owner_type=OWNER_KNOWLEDGE_CHUNK,
            )

        async with factory() as session:
            started = time.perf_counter()
            ann_hits = await PgVectorIndex(session).search(
                company_id=real_company,
                model=MODEL,
                query_vector=query,
                limit=TOP_K,
                owner_type=OWNER_KNOWLEDGE_CHUNK,
            )
            latencies.append((time.perf_counter() - started) * 1000)

        exact_ids.append([hit.embedding_id for hit in exact_hits])
        ann_ids.append([hit.embedding_id for hit in ann_hits])

        owners = {hit.embedding_id for hit in ann_hits}
        if owners:
            async with factory() as session:
                belongs = await session.execute(
                    text(
                        "SELECT count(*) FROM embeddings WHERE id = ANY(:ids) "
                        "AND company_id <> :company_id"
                    ),
                    {"ids": [str(o) for o in owners], "company_id": str(real_company)},
                )
                foreign_rows += int(belongs.scalar_one())

    recall = statistics.mean(
        len(set(a) & set(e)) / len(e) if e else 1.0
        for a, e in zip(ann_ids, exact_ids, strict=True)
    )
    exact_top1 = sum(1 for a, e in zip(ann_ids, exact_ids, strict=True) if a[:1] == e[:1])
    empty = sum(1 for a in ann_ids if not a)

    print()
    print("--- tenant isolation ---")
    print(f"rows from another company in ANN results : {foreign_rows}  (must be 0)")
    print(f"queries returning nothing                : {empty}/{QUERIES}  (must be 0)")
    print()
    print("--- parity with the exact index ---")
    print(f"recall@{TOP_K} vs exact                       : {recall:.3f}")
    print(f"top-1 agreement                          : {exact_top1}/{QUERIES}")
    print()
    print("--- latency (ANN, filtered to one tenant) ---")
    print(f"p50 : {statistics.median(latencies):.1f} ms")
    print(f"p95 : {sorted(latencies)[int(len(latencies) * 0.95) - 1]:.1f} ms")
    print(f"max : {max(latencies):.1f} ms")

    async with factory() as session:
        await session.execute(
            text("DELETE FROM embeddings WHERE model = :model"), {"model": MODEL}
        )
        await session.commit()
    await engine.dispose()

    failures = []
    if foreign_rows:
        failures.append(f"{foreign_rows} cross-tenant rows leaked into results")
    if empty:
        failures.append(f"{empty} queries returned nothing for a small tenant")
    if recall < 0.95:
        failures.append(f"recall {recall:.3f} below 0.95")

    if failures:
        print("\nFAILED: " + "; ".join(failures))
        return 1
    print("\nPASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
