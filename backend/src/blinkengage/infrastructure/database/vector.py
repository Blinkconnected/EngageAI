"""A vector column that is a real ``vector`` on PostgreSQL and portable
text on SQLite — the same dialect-branching shape ``GUID`` already uses in
``infrastructure/database/base.py``.

This exists because of a constraint this codebase states explicitly and
has paid to keep: the test suite runs against in-memory SQLite and starts
no external services, so ``custom_fields`` stays portable ``JSON`` rather
than ``JSONB`` and ``date_trunc`` bucketing was folded into the service
layer rather than into repositories. A ``vector`` column violates that
rule head-on, so it is confined here, behind one type decorator, exactly
as the UUID/CHAR(36) split was.

Deliberately **no dependency on the ``pgvector`` Python package.** The
storage format is a documented, stable text form (``[0.1,0.2,0.3]``) that
PostgreSQL casts natively, and the two things the package would add — a
column type and comparison operators — are three lines and one SQL
operator respectively. Adding a dependency would mean rebuilding every
image for what a ``UserDefinedType`` expresses directly, and the
dependency-scan surface is not free (see the note in ``pyproject.toml``
about dropping ``black``).

What PostgreSQL *does* need is the extension itself: ``CREATE EXTENSION
vector``, which the migration performs and which the stock
``postgres:17-alpine`` image does not carry. The compose file therefore
pins ``pgvector/pgvector:pg17``.
"""

from typing import Any

from sqlalchemy import Text
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator, TypeEngine, UserDefinedType


class PgVector(UserDefinedType[list[float]]):
    """The bare PostgreSQL ``vector(n)`` type.

    Used only through ``Vector`` below; it exists separately because
    ``load_dialect_impl`` has to hand SQLAlchemy something that knows how
    to render its own DDL.
    """

    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **_kw: Any) -> str:
        return f"vector({self.dimensions})"


class Vector(TypeDecorator[list[float]]):
    """Stores a fixed-width float vector.

    The width is fixed at column-definition time because an HNSW index
    requires it — an unconstrained ``vector`` column cannot be indexed,
    which would defeat the entire purpose. Changing the width is
    therefore a migration and a full backfill, never a settings edit;
    ``EmbeddingService`` refuses to write a vector whose length disagrees
    with the configured width rather than letting the database reject it
    partway through a batch.
    """

    impl = Text
    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        super().__init__()
        self.dimensions = dimensions

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PgVector(self.dimensions))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: list[float] | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if len(value) != self.dimensions:
            raise ValueError(f"expected a {self.dimensions}-dimensional vector, got {len(value)}")
        return to_pgvector_literal(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> list[float] | None:
        if value is None:
            return None
        if isinstance(value, list):
            return [float(item) for item in value]
        return from_pgvector_literal(str(value))


def to_pgvector_literal(vector: list[float] | tuple[float, ...]) -> str:
    """``[0.1,0.2]`` — the text form PostgreSQL casts to ``vector``.

    ``repr`` is used rather than a fixed precision so a float round-trips
    exactly. Truncating here would make a stored vector differ from the
    one that was embedded, which is a silent, permanent, un-diagnosable
    accuracy loss on every row.
    """
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"


def from_pgvector_literal(literal: str) -> list[float]:
    trimmed = literal.strip()
    if trimmed.startswith("[") and trimmed.endswith("]"):
        trimmed = trimmed[1:-1]
    if not trimmed:
        return []
    return [float(part) for part in trimmed.split(",")]
