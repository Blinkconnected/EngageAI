"""platform settings (SMTP relay configurable from the console)

See ``docs/architecture/platform-admin.md``.

One row per settings group, the value encrypted as a whole rather than
one column at a time — an SMTP password is a real credential, and
encrypting the row means a field added later is protected by default
instead of by whoever remembers.

No backfill. An installation with no row keeps running on its
environment variables, which is what every existing deployment does
today; the stored value overrides the environment rather than replacing
it.

Revision ID: b18e4c7d2a91
Revises: e7d3b95c1042
Create Date: 2026-07-29 18:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b18e4c7d2a91"
down_revision: str | None = "e7d3b95c1042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_settings",
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("value", sa.LargeBinary(), nullable=False),
        sa.Column("updated_by_email", sa.String(length=255), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("platform_settings")
