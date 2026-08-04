"""``PgVectorIndex`` — approximate nearest-neighbour search through
pgvector's HNSW index.

The whole design of this adapter is about one hazard, which is worth
stating plainly because the broken version looks identical in review:

**An ANN index ranks before predicates apply.** A query written as "find
the 10 nearest vectors, then keep the ones belonging to company A" walks
the index, collects candidates from the whole installation, and *then*
discards the ones from other tenants. For a small tenant on a large
installation the surviving count is frequently zero. Nothing errors, the
query is fast, and the symptom is "semantic search finds nothing for our
smaller customers" — which reads as a relevance problem and gets tuned
rather than fixed.

Two mechanisms, both required:

1. **The predicate is in the SQL**, so PostgreSQL can push it into the
   index scan rather than applying it afterwards.
2. **``hnsw.iterative_scan``** tells pgvector to keep pulling batches from
   the index until the filter has yielded enough rows, instead of
   truncating at the first ``ef_search`` batch. Without it, mechanism 1
   still returns short for a selective filter.

Set per transaction with ``SET LOCAL``, never ``SET``: a pooled
connection carries session state to whoever gets it next, so a plain
``SET`` here would silently change the behaviour of unrelated queries on
the same connection for the rest of its life.
"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.domain.vector_index import VectorIndex, VectorMatch
from blinkengage.infrastructure.database.vector import to_pgvector_literal

# `relaxed_order` lets pgvector return results slightly out of order in
# exchange for not having to buffer the whole scan. Retrieval re-ranks
# through Reciprocal Rank Fusion immediately afterwards, so exact ANN
# ordering is not something downstream depends on — and `strict_order`
# costs materially more for a guarantee this pipeline discards.
_ITERATIVE_SCAN_MODE = "relaxed_order"

# How hard the index works per query. 100 is well above pgvector's default
# of 40: recall matters more than latency here because a missed chunk is a
# wrong answer, while the query is one indexed scan either way.
DEFAULT_EF_SEARCH = 100


class PgVectorIndex(VectorIndex):
    def __init__(
        self,
        session: AsyncSession,
        *,
        ef_search: int = DEFAULT_EF_SEARCH,
        max_scan_tuples: int = 20_000,
    ) -> None:
        self._session = session
        self._ef_search = ef_search
        self._max_scan_tuples = max_scan_tuples

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

        await self._session.execute(text(f"SET LOCAL hnsw.iterative_scan = {_ITERATIVE_SCAN_MODE}"))
        await self._session.execute(text(f"SET LOCAL hnsw.ef_search = {int(self._ef_search)}"))
        # A ceiling on how much of the index one query may walk when the
        # filter is very selective. Without it, a company with no matching
        # rows at all would scan the entire index before concluding that.
        await self._session.execute(
            text(f"SET LOCAL hnsw.max_scan_tuples = {int(self._max_scan_tuples)}")
        )

        owner_clause = "AND owner_type = :owner_type" if owner_type is not None else ""
        # `1 - (vector <=> query)` converts pgvector's cosine *distance*
        # into the cosine *similarity* `VectorMatch` is documented to
        # carry, so every scorer in the retrieval stack agrees on which
        # direction "better" runs.
        statement = text(
            f"""
            SELECT id, owner_type, owner_id,
                   1 - (vector <=> CAST(:query_vector AS vector)) AS score
              FROM embeddings
             WHERE company_id = :company_id
               AND model = :model
               {owner_clause}
             ORDER BY vector <=> CAST(:query_vector AS vector), id
             LIMIT :limit
            """
        )
        params: dict[str, object] = {
            "company_id": str(company_id),
            "model": model,
            "query_vector": to_pgvector_literal(list(query_vector)),
            "limit": limit,
        }
        if owner_type is not None:
            params["owner_type"] = owner_type

        result = await self._session.execute(statement, params)
        return [
            VectorMatch(
                owner_type=row.owner_type,
                owner_id=(
                    row.owner_id if isinstance(row.owner_id, UUID) else UUID(str(row.owner_id))
                ),
                embedding_id=row.id if isinstance(row.id, UUID) else UUID(str(row.id)),
                score=float(row.score),
            )
            for row in result
        ]
