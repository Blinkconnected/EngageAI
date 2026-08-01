"""four SLA clocks per conversation

See ``docs/architecture/sla-engine.md``.

One row per clock rather than sixteen columns on ``conversations``, because
the four are genuinely independent: a service may measure some and not others,
each pauses for its own reason at its own moment, each carries its own elapsed
time. Columns would make every conversation carry four sets of nullable fields
and turn "show me every clock paused for business hours" into a four-way OR.

**Mutable, unlike the timeline.** This is where each clock currently stands;
how it got there is the append-only decision log. Two representations of the
same thing deliberately — one answers "where does this stand" in a single
indexed read, the other "how did it get here", and neither derives cheaply
from the other.

``target_minutes`` is copied from the service version rather than read through
it: a conversation's targets are frozen at its start, so an administrator
halving a target at noon must not move the deadline of everything already
running.

``due_at`` is materialised so the sweep finds what is due with one indexed
range scan instead of recomputing a deadline per row, and is **null whenever
the clock is not running** — which keeps a paused clock out of the sweep
entirely rather than relying on the sweep to filter it out.

No backfill. Conversations that predate this have no clocks, and reconstructing
a deadline for a conversation whose service targets may since have changed
would put a guess where a measurement belongs. The clocks start on the next
conversation.

Revision ID: f6d1b83c07e5
Revises: e3c05a91f7d8
Create Date: 2026-08-01 19:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision: str = "f6d1b83c07e5"
down_revision: str | None = "e3c05a91f7d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_sla_clocks",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "conversation_id",
            GUID(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            GUID(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("timer", sa.String(20), nullable=False),
        sa.Column("state", sa.String(20), nullable=False, server_default="NOT_MEASURED"),
        sa.Column("target_minutes", sa.Integer(), nullable=True),
        sa.Column("elapsed", sa.Interval(), nullable=False, server_default=sa.text("'0'")),
        sa.Column("running_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pause_reason", sa.String(30), nullable=True),
        sa.Column("pause_note", sa.String(500), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("warned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    # Two clocks of the same kind on one conversation is a state with no
    # meaning; the constraint makes a retry idempotent rather than doubling.
    op.create_index(
        "uq_conversation_sla_clocks",
        "conversation_sla_clocks",
        ["conversation_id", "timer"],
        unique=True,
    )
    op.create_index(
        "ix_conversation_sla_clocks_due",
        "conversation_sla_clocks",
        ["company_id", "due_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_sla_clocks_due", table_name="conversation_sla_clocks")
    op.drop_index("uq_conversation_sla_clocks", table_name="conversation_sla_clocks")
    op.drop_table("conversation_sla_clocks")
