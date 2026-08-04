"""A clock records which configuration set its deadline.

``target_minutes`` has always been copied onto the clock rather than read
through a join, so an administrator halving a target at noon does not move the
deadline of everything already running. ``target_source`` is the same fact's
other half: *who* set it.

It became necessary when SLA targets stopped having one possible origin.
Targets now resolve service → queue → platform default, so "due in three
minutes" has three possible authors, and reconstructing which one afterwards
would mean re-reading a service version, a queue and a policy **as they stand
now** — a configuration that may have changed since the clock started, which
is precisely the problem freezing the target already solved.

Nullable, with no backfill. Clocks started before this column existed genuinely
do not know their source, and inferring one from today's configuration would
be a guess presented as a record. On this installation the question is
academic: ``conversation_sla_clocks`` holds zero rows, because the defect this
change fixes meant no clock had ever started anywhere.

Revision ID: e3c7d1a94f28
Revises: d1f7a3c85b92
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e3c7d1a94f28"
down_revision: str | None = "d1f7a3c85b92"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversation_sla_clocks",
        sa.Column("target_source", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversation_sla_clocks", "target_source")
