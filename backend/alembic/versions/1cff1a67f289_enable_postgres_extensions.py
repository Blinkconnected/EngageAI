"""enable postgres extensions

Revision ID: 1cff1a67f289
Revises: 
Create Date: 2026-07-23 00:32:03.980704
"""

from collections.abc import Sequence

from alembic import op

revision: str = "1cff1a67f289"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "citext"')


def downgrade() -> None:
    op.execute('DROP EXTENSION IF EXISTS "citext"')
    op.execute('DROP EXTENSION IF EXISTS "pgcrypto"')
