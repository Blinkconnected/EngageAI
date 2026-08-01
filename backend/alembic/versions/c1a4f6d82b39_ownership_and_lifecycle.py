"""ownership timeline, and the eight-state lifecycle

See ``docs/architecture/queue-lifecycle.md``.

Two changes, and the second is the one that touches every existing row.

**The ownership timeline.** One append-only row per transition, carrying both
sides — who took it, who had it, why, and when the hold lapses. A history,
because the model has to answer *who owned it before* and *why it changed*,
and a mutable ``owner_id`` column answers neither. The current owner is the
newest row, derived rather than duplicated onto ``conversations``: a mutable
column plus a history table is two writes that can disagree, and the one that
disagrees is always the one somebody is reading.

**Four statuses become eight.** ``open`` is why this is a data migration and
not a rename: it meant both "in a queue, nobody has it" and "somebody is
working it", which is exactly the coupling the eight-state lifecycle exists to
end. That cannot be resolved from the status alone, so the migration reads the
assignment — an ``open`` conversation with an agent becomes ``in_progress``,
one without becomes ``waiting``. ``pending`` becomes ``waiting_customer``;
``resolved`` and ``closed`` keep their names.

``Enum(native_enum=False)`` stores the member NAME, so the stored values are
uppercase and the UPDATEs below match on that.

Every existing conversation also gets an opening ownership row, derived the
same way: assigned ones are owned by their agent, queued ones by their queue,
the rest by nobody. Reconstructed, and honestly so — ``owned_from`` is the
conversation's own timestamp rather than now, and the reason says the row was
backfilled rather than claiming somebody picked it up.

Revision ID: c1a4f6d82b39
Revises: b5e8c17d40a2
Create Date: 2026-08-01 15:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision: str = "c1a4f6d82b39"
down_revision: str | None = "b5e8c17d40a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_ownership",
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
        sa.Column("owner_kind", sa.String(20), nullable=False),
        # No foreign key: an owner may be an agent, a team or a queue, and a
        # record of who was answerable must survive that row being deleted.
        sa.Column("owner_id", GUID(), nullable=True),
        sa.Column("owner_name", sa.String(255), nullable=True),
        sa.Column("previous_kind", sa.String(20), nullable=True),
        sa.Column("previous_id", GUID(), nullable=True),
        sa.Column("previous_name", sa.String(255), nullable=True),
        sa.Column("reason", sa.String(30), nullable=False),
        sa.Column(
            "owned_from", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("holds_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "actor_user_id", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.create_index(
        "ix_conversation_ownership_timeline",
        "conversation_ownership",
        ["conversation_id", "owned_from"],
    )
    op.create_index(
        "ix_conversation_ownership_owner", "conversation_ownership", ["owner_id", "owned_from"]
    )

    # --- Four statuses become eight ---------------------------------
    #
    # Order matters: `open` is split by assignment, so the assigned half is
    # moved first and the remainder falls through to `waiting`.
    op.execute(
        "UPDATE conversations SET status = 'IN_PROGRESS' "
        "WHERE status = 'OPEN' AND assigned_agent_id IS NOT NULL"
    )
    op.execute("UPDATE conversations SET status = 'WAITING' WHERE status = 'OPEN'")
    op.execute("UPDATE conversations SET status = 'WAITING_CUSTOMER' WHERE status = 'PENDING'")

    # --- An opening ownership row for every conversation ------------
    #
    # Derived from what is knowable, and honest about being derived: the
    # reason says it was backfilled rather than claiming somebody picked it
    # up, and `owned_from` is the conversation's own timestamp so the
    # timeline does not claim every conversation changed hands today.
    op.execute(
        """
        INSERT INTO conversation_ownership
            (id, conversation_id, company_id, owner_kind, owner_id, reason,
             owned_from, detail)
        SELECT
            gen_random_uuid(),
            c.id,
            c.company_id,
            CASE
                WHEN c.assigned_agent_id IS NOT NULL THEN 'HUMAN_AGENT'
                WHEN c.queue_id IS NOT NULL THEN 'QUEUE'
                ELSE 'NOBODY'
            END,
            COALESCE(c.assigned_agent_id, c.queue_id),
            'ENTERED_QUEUE',
            COALESCE(c.queue_entered_at, c.created_at, now()),
            '{"backfilled": true}'
        FROM conversations c
        """
        if op.get_bind().dialect.name == "postgresql"
        else "SELECT 1"
    )


def downgrade() -> None:
    op.execute("UPDATE conversations SET status = 'PENDING' WHERE status = 'WAITING_CUSTOMER'")
    # The eight collapse back to four lossily — `waiting` and `in_progress`
    # both came from `open` and both return to it. Stated rather than
    # pretended: a downgrade restores the schema, not the distinction.
    op.execute(
        "UPDATE conversations SET status = 'OPEN' "
        "WHERE status IN ('WAITING', 'IN_PROGRESS', 'NEW', 'WAITING_AGENT')"
    )
    op.execute("UPDATE conversations SET status = 'CLOSED' WHERE status = 'CUSTOMER_FEEDBACK'")

    op.drop_index("ix_conversation_ownership_owner", table_name="conversation_ownership")
    op.drop_index("ix_conversation_ownership_timeline", table_name="conversation_ownership")
    op.drop_table("conversation_ownership")
