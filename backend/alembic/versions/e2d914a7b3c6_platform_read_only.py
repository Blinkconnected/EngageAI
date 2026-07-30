"""read-only platform administrators

See ``docs/architecture/platform-admin.md``.

Platform authority is otherwise all-or-nothing, deliberately, so that no
tenant role can be edited into it. This flag does not weaken that: it only
ever **narrows** what an operator can do, and a strictly less powerful
principal cannot be an escalation path.

It exists so somebody who needs to audit pricing — a finance analyst
reviewing what a customer is charged, or an auditor tracing a change —
does not need the authority to change it. Read access without write access
is the normal shape of that job, and the alternative is sharing an account
that can rewrite prices.

Backfilled to false: every existing platform administrator keeps the
authority they have. Widening on a migration would be the wrong default in
one direction; silently removing it would be the wrong default in the
other.

Revision ID: e2d914a7b3c6
Revises: b73f2a8e14c9
Create Date: 2026-07-29 23:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e2d914a7b3c6"
down_revision: str | None = "b73f2a8e14c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "platform_read_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "platform_read_only")
