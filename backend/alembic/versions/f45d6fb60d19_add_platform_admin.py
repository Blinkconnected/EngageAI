"""Add platform (super) administrators

Revision ID: f45d6fb60d19
Revises: 34919b8bff0b
Create Date: 2026-07-29

A platform administrator operates the whole installation rather than a
tenant: listing companies, suspending and reactivating them, and (in a
later milestone) managing their subscriptions. They deliberately have no
access to any tenant's conversations, customers or messages — see
``docs/architecture/platform-admin.md``.

Two changes make that principal representable:

- ``users.company_id`` becomes **nullable**. It was NOT NULL, which made
  a company-less identity impossible. Every ordinary user still belongs
  to exactly one company; NULL means "platform".
- ``users.is_platform_admin`` is a new flag, deliberately a column rather
  than an RBAC role: ``roles.company_id`` is NOT NULL so a cross-tenant
  role cannot exist, and keeping platform authority outside the tenant
  permission catalog means no tenant role can ever be edited into it.

Note the partial unique index on ``users.email`` (migration
``040a7da326b5``) is unaffected and still applies — a platform admin's
email is unique against every tenant user's, as it must be, since login
resolves an email to exactly one identity.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f45d6fb60d19"
down_revision: str | None = "34919b8bff0b"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("users", "company_id", existing_type=sa.Uuid(), nullable=True)
    op.add_column(
        "users",
        sa.Column(
            "is_platform_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    # Platform admins have no company to fall back to, so restoring the
    # NOT NULL constraint means removing them outright. Deleting rather
    # than failing keeps the downgrade actually runnable; there is no
    # tenant data to lose, since a platform admin never owned any.
    op.execute(sa.text("DELETE FROM users WHERE company_id IS NULL"))
    op.drop_column("users", "is_platform_admin")
    op.alter_column("users", "company_id", existing_type=sa.Uuid(), nullable=False)
