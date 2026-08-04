"""``VectorIndex`` — the similarity-search port.

Two implementations exist and must agree: a pgvector/HNSW adapter for
PostgreSQL, and an exact brute-force adapter used by the test suite (which
runs on SQLite and starts no external services). The exact adapter doubles
as the *reference* implementation — a property test asserts both return
the same ordering for the same inputs, which is how an ANN parameter
mistake gets caught rather than silently degrading recall in production.

**Tenant isolation is structural here, not conventional.** ``company_id``
is a required keyword argument on the only search method, so there is no
way to express a search that spans companies — a caller cannot forget a
filter it has no way to omit. This matters more for vector search than
for ordinary queries: an ANN index ranks *before* predicates apply, so a
"search then filter" implementation would return whatever fraction of its
top-k happened to belong to the right tenant, which for a small tenant on
a large installation is frequently zero. That failure looks like poor
relevance, not like a leak, so it survives review.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class VectorMatch:
    """One similarity hit.

    ``score`` is cosine **similarity** in ``[-1, 1]``, higher is better —
    deliberately not the cosine *distance* pgvector's ``<=>`` operator
    returns, so that every scorer in the retrieval stack agrees on the
    direction of "better" and no caller has to remember which way a
    particular number runs.
    """

    owner_type: str
    owner_id: UUID
    embedding_id: UUID
    score: float


class VectorIndex(ABC):
    @abstractmethod
    async def search(
        self,
        *,
        company_id: UUID,
        model: str,
        query_vector: Sequence[float],
        limit: int,
        owner_type: str | None = None,
    ) -> list[VectorMatch]:
        """Nearest neighbours within one company, for one embedding model.

        ``model`` is required and always filtered on. A partially
        completed model migration otherwise returns a mixture of two
        models' vectors ranked against each other, which is not a
        degraded result but a meaningless one — filtering means an
        incomplete backfill returns *fewer* results rather than wrong
        ones.
        """
