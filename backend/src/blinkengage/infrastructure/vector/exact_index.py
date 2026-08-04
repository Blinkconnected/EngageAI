"""``ExactVectorIndex`` — exhaustive cosine search, in Python.

Two jobs, and the second is the important one.

It is what the test suite uses, because the suite runs on in-memory
SQLite and starts no external services, and SQLite has no vector type or
ANN index to search with.

It is also the **reference implementation**. ``HNSW`` is an approximate
index: it trades recall for speed, and a badly chosen ``ef_search`` or a
filter applied in the wrong order degrades results *silently* — nothing
errors, queries stay fast, and answers quietly get worse. A test asserting
that the pgvector adapter returns the same ordering as this one for the
same inputs is the only thing that catches that, which is why this is
production code rather than a fixture.

It scans, so it is O(rows in the tenant). ``max_scan`` bounds that
explicitly rather than letting a large tenant discover the limit as a
timeout, and the bound is reported honestly: exceeding it is a
configuration error, not a silently truncated result.
"""

import math
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.domain.vector_index import VectorIndex, VectorMatch
from blinkengage.infrastructure.database.models.embedding import Embedding

DEFAULT_MAX_SCAN = 50_000


class ExactVectorIndex(VectorIndex):
    def __init__(self, session: AsyncSession, *, max_scan: int = DEFAULT_MAX_SCAN) -> None:
        self._session = session
        self._max_scan = max_scan

    async def search(
        self,
        *,
        company_id: UUID,
        model: str,
        query_vector: Sequence[float],
        limit: int,
        owner_type: str | None = None,
    ) -> list[VectorMatch]:
        if limit <= 0 or not query_vector:
            return []

        # company_id and model are applied in the query, not after it.
        # Filtering in Python would still be correct here (the scan is
        # exhaustive) but it would diverge from the pgvector adapter,
        # where filtering after ranking is the actual bug this design
        # exists to prevent — and a reference implementation that differs
        # structurally from the thing it verifies is not a reference.
        statement = select(Embedding).where(
            Embedding.company_id == company_id,
            Embedding.model == model,
        )
        if owner_type is not None:
            statement = statement.where(Embedding.owner_type == owner_type)

        rows = list(
            (await self._session.execute(statement.limit(self._max_scan + 1))).scalars().all()
        )
        if len(rows) > self._max_scan:
            raise RuntimeError(
                f"ExactVectorIndex would scan more than {self._max_scan} rows for company "
                f"{company_id}; use the pgvector index for a corpus this size"
            )

        query_norm = math.sqrt(sum(value * value for value in query_vector))
        if query_norm == 0.0:
            return []

        scored: list[tuple[float, Embedding]] = []
        for row in rows:
            vector = row.vector
            if len(vector) != len(query_vector):
                # A row written under a different width than the query.
                # Only reachable mid-migration; skipping is right, because
                # the alternative is comparing vectors of different widths,
                # which is not a worse answer but a meaningless one.
                continue
            norm = math.sqrt(sum(value * value for value in vector))
            if norm == 0.0:
                continue
            dot = sum(a * b for a, b in zip(vector, query_vector, strict=True))
            scored.append((dot / (norm * query_norm), row))

        # Sorted by score descending, then by id, so equal scores order
        # identically on every run and across both adapters — an
        # unspecified tie-break makes the parity test flaky and every
        # retrieval trace unreproducible.
        scored.sort(key=lambda pair: (-pair[0], str(pair[1].id)))
        return [
            VectorMatch(
                owner_type=row.owner_type,
                owner_id=row.owner_id,
                embedding_id=row.id,
                score=score,
            )
            for score, row in scored[:limit]
        ]
