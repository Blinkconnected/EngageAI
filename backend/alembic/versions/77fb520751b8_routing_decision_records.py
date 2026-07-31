"""routing decision records

See ``docs/architecture/queues-routing.md``.

One append-only table holding *why* each conversation went where it went:
which rule matched, which strategy ran, who was passed over, and — when
nothing happened — why nothing happened. Plus a trigger that refuses
UPDATE and DELETE outright, so "a decision is a historical fact" survives
a ``psql`` session and not merely repository discipline. Correcting a
decision means recording another one, exactly as a ledger mistake is
corrected by posting the opposite entry.

No backfill, deliberately. Unlike ``ledger_entries`` — which was declared
the source of truth for balances and so could not start out disagreeing
with the invoices that already existed — a routing decision records an
observation made at a single instant that has already passed. Every
existing conversation's rules may since have been edited or deleted, and
a reconstructed "this is probably why it was routed there" would be a
guess presented in the same table as measurements. The table starts empty
and fills from the next inbound conversation onward; a conversation that
predates it honestly has no decision rather than a fabricated one.

Revision ID: 77fb520751b8
Revises: 611ce623fac4
Create Date: 2026-07-31 20:58:10.826135
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "77fb520751b8"
down_revision: str | None = "611ce623fac4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        "routing_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Enum(native_enum=False) columns: an application-level VARCHAR
        # storing the member NAME, not a Postgres native enum type — so a
        # later milestone adding AI_RELEASED/SLA_PAUSED is a pure code
        # change with no migration, the same property queues-routing.md
        # already records for assignment_strategy and agent status.
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=40), nullable=False),
        # No foreign keys on the four columns below, on purpose. A
        # SET NULL on a deleted queue/agent/rule would erase the very fact
        # the row exists to hold, and a RESTRICT would make an audit table
        # block ordinary administration. The accompanying *_name columns
        # are what keep the row readable once the referent is gone.
        sa.Column("selected_queue_id", sa.Uuid(), nullable=True),
        sa.Column("selected_queue_name", sa.String(length=255), nullable=True),
        sa.Column("selected_agent_id", sa.Uuid(), nullable=True),
        sa.Column("selected_agent_name", sa.String(length=255), nullable=True),
        sa.Column("matched_rule_id", sa.Uuid(), nullable=True),
        sa.Column("matched_rule_name", sa.String(length=500), nullable=True),
        sa.Column("matched_rule_priority", sa.Integer(), nullable=True),
        sa.Column("rules_evaluated", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("strategy", sa.String(length=30), nullable=True),
        sa.Column(
            "candidates_considered", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("rejected_candidates", sa.JSON(), nullable=False),
        sa.Column("rejections_omitted", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("sentence", sa.Text(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        # CASCADE on both, unlike ledger_entries' SET NULL: a decision is
        # only meaningful *about* a conversation, so one that outlived its
        # conversation would be an orphan nobody could read rather than
        # evidence worth keeping.
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # The two queries that matter, and the only two: one conversation's
    # decisions in order, and a company's most recent ones.
    op.create_index(
        "ix_routing_decisions_conversation",
        "routing_decisions",
        ["conversation_id", "decided_at"],
    )
    op.create_index(
        "ix_routing_decisions_company_recent",
        "routing_decisions",
        ["company_id", "decided_at"],
    )

    if _is_postgres():
        op.execute(
            """
            CREATE OR REPLACE FUNCTION routing_decisions_append_only()
            RETURNS TRIGGER AS $$
            BEGIN
              -- Two adjacent literals separated by a newline are one
              -- constant in PostgreSQL, which is how this message stays
              -- inside the line limit without being abbreviated.
              RAISE EXCEPTION
                'routing_decisions is append-only; a decision is a historical '
                'fact, and correcting one means recording another';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_routing_decisions_immutable
            BEFORE UPDATE OR DELETE ON routing_decisions
            FOR EACH ROW EXECUTE FUNCTION routing_decisions_append_only()
            """
        )


def downgrade() -> None:
    if _is_postgres():
        op.execute("DROP TRIGGER IF EXISTS trg_routing_decisions_immutable ON routing_decisions")
        op.execute("DROP FUNCTION IF EXISTS routing_decisions_append_only()")
    op.drop_index("ix_routing_decisions_company_recent", table_name="routing_decisions")
    op.drop_index("ix_routing_decisions_conversation", table_name="routing_decisions")
    op.drop_table("routing_decisions")
