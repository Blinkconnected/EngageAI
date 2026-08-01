"""Time arithmetic that means the same thing on both databases.

PostgreSQL runs production; SQLite runs the tests. They disagree about
timestamps in a way that does not raise, which is the dangerous kind: SQLite
will happily subtract two timestamps as if they were numbers and hand back a
figure wrong by a factor of billions rather than refusing.

That is not hypothetical — it shipped a report showing ownership durations of
minus two hundred and ten billion seconds, and it was only caught because the
number was absurd enough to notice. A duration that was merely wrong by 15%
would have been believed. So the conversion lives in one place, with a test
that runs on both dialects, instead of being written out at each call site.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Float, cast, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement


def seconds_between(session: AsyncSession, *, later: Any, earlier: Any) -> ColumnElement[float]:
    """Seconds from ``earlier`` to ``later``, negative if they are reversed.

    PostgreSQL subtracts timestamps into an interval that ``EXTRACT(EPOCH …)``
    reads back as seconds. SQLite has neither operation, so the two moments go
    through ``julianday`` — fractional days — and are scaled by hand.
    """
    if session.get_bind().dialect.name == "sqlite":
        return cast((func.julianday(later) - func.julianday(earlier)) * 86400.0, Float)
    return cast(func.extract("epoch", later - earlier), Float)


__all__ = ["seconds_between"]
