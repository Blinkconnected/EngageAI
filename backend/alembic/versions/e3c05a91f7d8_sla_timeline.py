"""routing decisions record the SLA clocks

See ``docs/architecture/sla-engine.md``.

Every SLA transition — started, paused, resumed, achieved, breached, stopped —
is written into the same log as the routing, service and policy decisions. Not
a table of its own, deliberately: an SLA transition *is* a decision the
platform made about a conversation, and a conversation is explained by reading
one history in order rather than by interleaving three by timestamp and hoping
the clocks agree.

Two columns and a blob, split by what somebody actually filters on. "Show me
every first-response breach" and "show me everything paused for business
hours" are real queries and get columns; "show me everything whose deadline
was 14:32" is not, and the rest goes in JSON.

The deadline is recorded on *every* SLA row, not only on pauses, because "why
did this deadline change?" is answered by comparing two of them — and a
deadline moves legitimately every time a clock pauses.

Adding columns to an append-only table is safe: the trigger refuses UPDATE and
DELETE of *rows*, and ALTER TABLE is neither. Existing rows get NULL, which is
honest — they were written before the clocks were recorded.

Revision ID: e3c05a91f7d8
Revises: d2b71e5c9a04
Create Date: 2026-08-01 18:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e3c05a91f7d8"
down_revision: str | None = "d2b71e5c9a04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("routing_decisions", sa.Column("sla_timer", sa.String(20), nullable=True))
    op.add_column("routing_decisions", sa.Column("sla_pause_reason", sa.String(30), nullable=True))
    op.add_column(
        "routing_decisions",
        sa.Column("sla_detail", sa.JSON(), nullable=False, server_default="{}"),
    )
    # "What did we breach, and on which clock" across a company. Partial on
    # PostgreSQL so it costs nothing for the routing, service and policy
    # decisions, which are most of the table.
    op.create_index(
        "ix_routing_decisions_sla",
        "routing_decisions",
        ["company_id", "sla_timer", "decided_at"],
        postgresql_where=sa.text("sla_timer IS NOT NULL"),
        sqlite_where=sa.text("sla_timer IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_routing_decisions_sla", table_name="routing_decisions")
    op.drop_column("routing_decisions", "sla_detail")
    op.drop_column("routing_decisions", "sla_pause_reason")
    op.drop_column("routing_decisions", "sla_timer")
