"""AI waits before taking a conversation, and says that it is waiting.

Two columns for one behaviour — AI Autopilot as a queue *worker* rather than
a first responder. Until now AI took an eligible conversation the instant it
arrived, so a human never had the chance to get there first, and the
``ai_pickup_delay_seconds`` a service could configure was read by nothing.

``conversations.ai_pickup_eligible_at`` is when AI may take it. Materialised
rather than derived from ``queue_entered_at`` plus the service's delay, so the
sweep is one indexed range scan instead of a join per row — the same reasoning
as ``conversation_sla_clocks.due_at``. Its index is partial: the column is null
for almost every row, since a conversation sits in it only for the few seconds
between arriving and being settled.

``routing_decisions.ai_pickup_delay_seconds`` is how long AI was told to wait,
carried on the decision rather than read back from the service. A service's
delay is editable through the ordinary admin screen, and a row that had to
join to it to be read would answer today's question with tomorrow's
configuration.

Backfill is deliberately nothing. Every existing conversation has already been
decided — AI either took it or did not — and inventing a pickup deadline for
conversations that are finished, or that AI was never eligible for, would put
rows into the sweep's index that the sweep would then have to reason about.
The new behaviour starts with the next conversation to arrive.

Revision ID: a4e79b2c1f60
Revises: f6d1b83c07e5
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a4e79b2c1f60"
down_revision: str | None = "f6d1b83c07e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("ai_pickup_eligible_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_conversations_ai_pickup",
        "conversations",
        ["ai_pickup_eligible_at"],
        unique=False,
        postgresql_where=sa.text("ai_pickup_eligible_at IS NOT NULL"),
    )
    op.add_column(
        "routing_decisions",
        sa.Column("ai_pickup_delay_seconds", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("routing_decisions", "ai_pickup_delay_seconds")
    op.drop_index("ix_conversations_ai_pickup", table_name="conversations")
    op.drop_column("conversations", "ai_pickup_eligible_at")
