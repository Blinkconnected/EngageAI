"""Carry a correlation id through the outbox.

The outbox is the seam where a request's identity was being lost. A
request arrives with a correlation id, does its work, writes a domain
event and returns; the relay picks that row up later, on a different
task, and publishes it. Without somewhere to put the id, every event
crossed that boundary anonymous, and the consumer logs on the other side
could not be tied back to the request that caused them.

Nullable and unindexed, deliberately:

- **Nullable** because rows written before this migration have no id, and
  because the relay must keep publishing events whose producer had no
  correlation context (a scheduled sweep, a replayed message). An event
  is never worth dropping over its metadata.
- **Unindexed** because nothing queries the outbox *by* correlation id —
  the relay reads by ``dispatched_at``, and correlation lookups happen in
  the log store, not here. An index on a hot insert path that no query
  uses is a write cost with no reader.

Revision ID: b7e4f2a86c15
Revises: a4d81f6b25c9
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7e4f2a86c15"
down_revision: str | None = "a4d81f6b25c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "event_outbox",
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("event_outbox", "correlation_id")
