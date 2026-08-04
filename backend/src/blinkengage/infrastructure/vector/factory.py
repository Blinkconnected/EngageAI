"""Selects the ``VectorIndex`` implementation matching the session's
dialect.

Branching on the dialect rather than on a setting, deliberately: which
index can run is a fact about the database in front of you, not a choice
an operator should be able to get wrong. A PostgreSQL deployment
configured to use the exact index would scan its entire corpus per query
and blame the feature; a SQLite one configured for pgvector would fail on
syntax that backend has never had. The same reasoning as ``GUID``'s
dialect branch, which nobody configures either.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.domain.vector_index import VectorIndex
from blinkengage.infrastructure.vector.exact_index import ExactVectorIndex
from blinkengage.infrastructure.vector.pgvector_index import PgVectorIndex


def build_vector_index(session: AsyncSession) -> VectorIndex:
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        return PgVectorIndex(session)
    return ExactVectorIndex(session)
