"""Add the financial audit trail

Revision ID: c844f6c83199
Revises: 21fac8ed2cd2
Create Date: 2026-07-29

The single source of truth for financial investigations — see
``docs/architecture/billing.md``.

One append-only table. Every creation, state transition, payment
allocation, credit note, cancellation and reversal writes a row carrying
the event type, the entity, **both** states, the actor, the timestamp, a
correlation ID and an optional reason.

Deliberately denormalized: the actor's email and name are stored as
values, not only as a foreign key, and amounts live on the event rather
than being read back from the document. An investigation that needs five
other tables to still hold their original values is not an audit trail.

A PostgreSQL trigger rejects UPDATE and DELETE outright. A trail that
can be edited is not evidence.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision: str = "c844f6c83199"
down_revision: str | None = "21fac8ed2cd2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "financial_audit_events",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("entity_id", GUID(), nullable=False),
        sa.Column("company_id", GUID(), nullable=True),
        sa.Column("previous_state", sa.String(length=30), nullable=True),
        sa.Column("new_state", sa.String(length=30), nullable=True),
        sa.Column("amount", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("actor_user_id", GUID(), nullable=True),
        sa.Column("actor_email", sa.String(length=255), nullable=True),
        sa.Column("actor_name", sa.String(length=255), nullable=True),
        sa.Column("actor_is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # SET NULL, never CASCADE: an audit row must outlive the company
        # it describes, or deleting a customer would erase the record of
        # what they were charged.
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_financial_audit_entity",
        "financial_audit_events",
        ["entity_type", "entity_id", "occurred_at"],
    )
    op.create_index(
        "ix_financial_audit_company", "financial_audit_events", ["company_id", "occurred_at"]
    )
    op.create_index("ix_financial_audit_correlation", "financial_audit_events", ["correlation_id"])

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION financial_audit_immutable() RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION
                'financial_audit_events is append-only; '
                'the audit trail is evidence and is never altered';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_financial_audit_immutable
              BEFORE UPDATE OR DELETE ON financial_audit_events
              FOR EACH ROW EXECUTE FUNCTION financial_audit_immutable()
            """
        )


def downgrade() -> None:
    """Drops the audit trail.

    Destructive in the strongest sense: this table is the record of what
    happened to every financial document, and nothing else reconstructs
    it.
    """
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_financial_audit_immutable ON financial_audit_events")
        op.execute("DROP FUNCTION IF EXISTS financial_audit_immutable()")
    op.drop_index("ix_financial_audit_correlation", table_name="financial_audit_events")
    op.drop_index("ix_financial_audit_company", table_name="financial_audit_events")
    op.drop_index("ix_financial_audit_entity", table_name="financial_audit_events")
    op.drop_table("financial_audit_events")
