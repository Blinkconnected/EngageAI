"""A conversation's SLA health, as something the database can sort by.

The Inbox is meant to open on what needs attention now, which means ordering
by health *before* anything else. Health is derived rather than stored, so
there are only two honest ways to do that: compute it for every row and sort
in Python, or teach the query to compute it.

Sorting in Python would sort the page — the fifty rows already chosen by some
other ordering — which is not sorting the Inbox at all. It would put the worst
of an arbitrary fifty at the top and leave a breached conversation on page
four. So the ranking is expressed in SQL.

The arithmetic is deliberately the *mirror image* of ``Clock.health``. That
one measures time consumed against the target; this one measures time
remaining against the deadline, because ``due_at`` is materialised on the row
and ``elapsed`` is an interval that neither database subtracts the same way.
The two are algebraically identical — ``counted / target`` and
``1 - remaining / target`` — and both read their bands from the same domain
constants, so a change to a threshold moves them together.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import Integer, case, cast, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import Subquery

from blinkengage.domain.sla import (
    AT_RISK_FRACTION,
    ATTENTION_FRACTION,
    SEVERITY,
    SlaHealth,
    SlaState,
)
from blinkengage.infrastructure.database.models.sla_clock import ConversationSlaClock
from blinkengage.infrastructure.database.sql_time import seconds_between

#: Slack on each band edge, in seconds, so a clock sitting *exactly* on a
#: boundary lands in the same band both ways.
#:
#: ``Clock.health`` compares timedeltas, which are exact. This compares
#: floats: PostgreSQL's ``EXTRACT(EPOCH …)`` is exact enough, but SQLite has
#: to route both moments through ``julianday`` — fractional days — and a
#: clock at precisely 60% of its target comes back as 2400.0000001 seconds
#: remaining rather than 2400, missing the edge by a ten-millionth of a
#: second and reading a band too healthy.
#:
#: A millisecond, on boundaries measured in minutes. Deliberately not larger:
#: this exists to absorb representation error, and a tolerance big enough to
#: absorb a real difference would be hiding the drift the tests check for.
_EDGE_TOLERANCE_SECONDS: float = 0.001

_BREACHED = SEVERITY[SlaHealth.BREACHED]
_AT_RISK = SEVERITY[SlaHealth.AT_RISK]
_ATTENTION = SEVERITY[SlaHealth.ATTENTION]
_HEALTHY = SEVERITY[SlaHealth.HEALTHY]


def clock_rank(session: AsyncSession, *, now: datetime) -> ColumnElement[int]:
    """One clock's severity, 0–3, matching ``Clock.health`` exactly."""
    remaining = seconds_between(session, later=ConversationSlaClock.due_at, earlier=now)
    target_seconds = ConversationSlaClock.target_minutes * 60.0

    return cast(
        case(
            (ConversationSlaClock.state == SlaState.BREACHED, literal(_BREACHED)),
            # Paused, achieved, stopped, never measured. A conversation
            # waiting on the customer is healthy — it is not the agent's
            # clock that is running — and an agent scanning the Inbox has to
            # be able to skip it without wondering whether they should.
            (ConversationSlaClock.state != SlaState.RUNNING, literal(_HEALTHY)),
            (ConversationSlaClock.target_minutes.is_(None), literal(_HEALTHY)),
            # A zero target is out of time the instant it starts. Reported,
            # not divided by: an administrator is allowed to save it, so the
            # query must not be the thing that discovers they did.
            (ConversationSlaClock.target_minutes <= 0, literal(_BREACHED)),
            # Running with no deadline should not occur — ``due_at`` is
            # written on every transition into RUNNING — but a row that
            # somehow has none must not sort as an emergency.
            (ConversationSlaClock.due_at.is_(None), literal(_HEALTHY)),
            (remaining <= _EDGE_TOLERANCE_SECONDS, literal(_BREACHED)),
            (
                remaining <= (1.0 - AT_RISK_FRACTION) * target_seconds + _EDGE_TOLERANCE_SECONDS,
                literal(_AT_RISK),
            ),
            (
                remaining <= (1.0 - ATTENTION_FRACTION) * target_seconds + _EDGE_TOLERANCE_SECONDS,
                literal(_ATTENTION),
            ),
            else_=literal(_HEALTHY),
        ),
        Integer,
    )


def conversation_ranks(
    session: AsyncSession,
    *,
    now: datetime,
    company_id: UUID,
    conversation_ids: Sequence[UUID] | None = None,
) -> Subquery:
    """Each conversation's worst clock, keyed by conversation.

    The worst, never the average — the same rule ``overall()`` follows. A
    conversation whose first response is twenty minutes overdue is not
    "mostly fine" because its resolution target is generous.

    ``company_id`` is required, not optional. Without it this aggregates every
    tenant's clocks before the join, so one company opening its Inbox would
    scan every other company's rows — a cost that is invisible on a test
    database and grows with the platform rather than with the query. It is
    also the tenant boundary, and a boundary with a default is one that gets
    forgotten.

    ``conversation_ids`` narrows further, for callers that already hold the
    rows they care about.

    Left-joined by callers rather than inner-joined, so a conversation with no
    clocks at all keeps its place in the list instead of vanishing from the
    Inbox. Those are real: a conversation on a service that measures nothing,
    and every conversation that predates the SLA engine.
    """
    query = select(
        ConversationSlaClock.conversation_id.label("conversation_id"),
        func.max(clock_rank(session, now=now)).label("rank"),
    ).where(ConversationSlaClock.company_id == company_id)
    if conversation_ids is not None:
        query = query.where(ConversationSlaClock.conversation_id.in_(conversation_ids))
    return query.group_by(ConversationSlaClock.conversation_id).subquery()


def health_of(rank: int | None) -> SlaHealth:
    """The band a rank came from. ``None`` — no clocks — is healthy."""
    if rank is None:
        return SlaHealth.HEALTHY
    for health, severity in SEVERITY.items():
        if severity == rank:
            return health
    return SlaHealth.HEALTHY


__all__ = ["clock_rank", "conversation_ranks", "health_of"]
