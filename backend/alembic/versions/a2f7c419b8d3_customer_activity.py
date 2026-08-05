"""conversations record who is waiting and since when

See ``docs/architecture/customer-activity.md`` — this is Phase A.

Six subsystems needed the same facts about a conversation's message history
and none could ask for them, so each inferred them differently. The worst
consequence is the one this fixes first: the platform could not tell whether a
customer was waiting for a reply, because ``last_message_at`` moves for
outbound messages too and ``operational_state()`` reports ``READY_FOR_REPLY``
when an *agent* holds the conversation rather than when the customer is
waiting.

**Columns on ``conversations``, not a side table.** The Inbox reads these on
every row of every page and the AI sweep filters on them across the whole
installation. A join for facts needed on every read is a join that gets
denormalised back within a milestone. The concept stays first-class — one
domain module, one projector, one guard — while the storage stays where it is
queried.

**Nullable and defaulted, read by nothing.** Phase A changes no behaviour
whatsoever: the columns exist and are empty until the projector (Phase B)
starts maintaining them and the backfill (Phase C) fills in the past. The
facts become true and provable before anything depends on them.

``awaiting_reply_since`` is indexed because the AI eligibility sweep's whole
question is "which conversations have been waiting longer than N", asked
across every company on a schedule. Partial, on the non-null rows, because a
conversation nobody is waiting on is the overwhelming majority and is never
what that query wants.

No ``customer_wait_duration`` column, deliberately. It changes every second,
so a stored value is wrong the moment after it is written — and a column that
is always stale is worse than no column, because somebody will read it and
believe it. It is computed on read from ``awaiting_reply_since``. What *is*
stored is ``last_wait_duration_seconds``: the settled figure, immutable once
written, which is the one every report actually wants.

Revision ID: a2f7c419b8d3
Revises: f6c3d95a2e81
Create Date: 2026-08-05 20:15:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a2f7c419b8d3"
down_revision: str | None = "f6c3d95a2e81"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("awaiting_reply_since", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("last_customer_message_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("conversations", sa.Column("last_customer_message_id", sa.Uuid(), nullable=True))
    op.add_column("conversations", sa.Column("last_agent_message_id", sa.Uuid(), nullable=True))
    op.add_column("conversations", sa.Column("last_ai_message_id", sa.Uuid(), nullable=True))
    op.add_column(
        "conversations",
        sa.Column(
            "unanswered_message_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "conversations", sa.Column("last_wait_duration_seconds", sa.Integer(), nullable=True)
    )

    # No foreign keys on the three message ids. They point at `messages`,
    # which is soft-deleted and retention-pruned: a FK would either block a
    # legitimate prune or cascade a NULL over the record of who last spoke.
    # These are evidence about the past, and the projector rebuilds them from
    # `messages` whenever they are questioned.

    op.create_index(
        "ix_conversations_awaiting_reply_since",
        "conversations",
        ["awaiting_reply_since"],
        postgresql_where=sa.text("awaiting_reply_since IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_awaiting_reply_since", table_name="conversations")
    op.drop_column("conversations", "last_wait_duration_seconds")
    op.drop_column("conversations", "unanswered_message_count")
    op.drop_column("conversations", "last_ai_message_id")
    op.drop_column("conversations", "last_agent_message_id")
    op.drop_column("conversations", "last_customer_message_id")
    op.drop_column("conversations", "last_customer_message_at")
    op.drop_column("conversations", "awaiting_reply_since")
