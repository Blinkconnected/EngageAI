"""Make users.email uniqueness deleted_at-aware (partial unique index)

Revision ID: 040a7da326b5
Revises: 59c384b4f2a7
Create Date: 2026-07-28

Replaces the plain, global unique index on ``users.email``
(``ix_users_email``, from ``f2df1379a476_add_companies_users_roles_permissions``)
with a partial unique index scoped to ``WHERE deleted_at IS NULL`` —
matching the pattern ``agents.user_id``'s own partial unique index
(``uq_agents_user_id``) already uses.

Without this, ``AgentService.delete()`` soft-deleting an agent's
underlying ``User`` row (see that service's own change, same release)
would still leave that email permanently blocking reuse: re-adding a new
agent with the exact same email would always fail with "already exists,"
no matter how long ago the original agent was deleted. This migration is
what makes that reuse actually possible at the database level, not just
in application code.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "040a7da326b5"
down_revision: str | None = "59c384b4f2a7"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_users_email", table_name="users")
    op.create_index(
        "ix_users_email",
        "users",
        ["email"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_users_email", table_name="users")
    op.create_index("ix_users_email", "users", ["email"], unique=True)
