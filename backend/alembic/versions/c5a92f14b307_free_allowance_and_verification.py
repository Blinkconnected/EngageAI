"""free monthly allowance and email verification

Two features, one migration, because they ship together.

**Free allowance.** ``included_quantity`` and ``billable_quantity`` on
both the usage snapshot and the invoice line. Backfilled so every
existing row reads ``included = 0, billable = quantity`` — which is
exactly what those documents already say. The rule that historical
invoices are never recalculated applies to this migration too: an
allowance introduced today must not retroactively discount a bill that
was already sent.

**Email verification.** ``users.email_verified_at`` and
``companies.verified_at``, plus a token table storing only the *hash* of
each token — a verification link is a bearer credential, and a database
backup containing raw tokens is a way to verify somebody else's account.

Existing companies are backfilled as **verified**. They signed up before
verification existed and have been using the product; suddenly locking
every one of them out of their own workspace would be a migration that
takes the installation down.

Revision ID: c5a92f14b307
Revises: b18e4c7d2a91
Create Date: 2026-07-29 18:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c5a92f14b307"
down_revision: str | None = "b18e4c7d2a91"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AMOUNT = sa.Numeric(precision=18, scale=6)


def _is_postgres() -> bool:
    """The immutability triggers are PostgreSQL-only; the SQLite test
    backend builds its schema from the ORM metadata and has none."""
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    # --- Free allowance -------------------------------------------
    for table in ("usage_period_lines", "invoice_lines"):
        op.add_column(
            table,
            sa.Column("included_quantity", _AMOUNT, nullable=False, server_default="0"),
        )
        op.add_column(
            table,
            sa.Column("billable_quantity", _AMOUNT, nullable=False, server_default="0"),
        )
        # Everything already billed was billed in full. Setting
        # billable = quantity preserves each document exactly as issued.
        #
        # Both tables carry an append-only trigger, and it refuses this
        # UPDATE — which is the protection working. A schema migration is
        # the one legitimate time to write to a frozen table, so the
        # trigger is disabled explicitly for the length of the backfill
        # and re-enabled immediately. Doing it in the open, in one
        # place, is far safer than a trigger written to tolerate
        # "some" updates: a rule with an exception is a rule somebody
        # will find a way through.
        if _is_postgres():
            op.execute(f"ALTER TABLE {table} DISABLE TRIGGER USER")
        op.execute(f"UPDATE {table} SET billable_quantity = quantity")  # noqa: S608
        if _is_postgres():
            op.execute(f"ALTER TABLE {table} ENABLE TRIGGER USER")

    # --- Email verification ---------------------------------------
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "companies",
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Everyone who signed up before verification existed keeps working.
    op.execute("UPDATE users SET email_verified_at = now()")
    op.execute("UPDATE companies SET verified_at = now()")

    op.create_table(
        "email_verification_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        # The hash, never the token. See domain/verification.py.
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_email_verification_token_hash",
        "email_verification_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_index("ix_email_verification_user", "email_verification_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_email_verification_user", table_name="email_verification_tokens")
    op.drop_index("ix_email_verification_token_hash", table_name="email_verification_tokens")
    op.drop_table("email_verification_tokens")
    op.drop_column("companies", "verified_at")
    op.drop_column("users", "email_verified_at")
    for table in ("usage_period_lines", "invoice_lines"):
        op.drop_column(table, "billable_quantity")
        op.drop_column(table, "included_quantity")
