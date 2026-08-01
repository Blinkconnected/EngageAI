"""routing decisions record which service was resolved

See ``docs/architecture/routing-rules.md``.

Four columns on ``routing_decisions``, so the decision that happens *before*
every other one is recorded like the rest: which service the conversation was
bound to, which version of it, and every stage the resolution pipeline ran on
the way there.

The stages matter as much as the winner. "Why did this go to Billing?" is
answered by what the earlier stages did *not* do — the customer was never
offered a menu, the keyword rules found nothing — as much as by the stage that
decided. A decision row holding only the outcome would make the pipeline a
black box with a receipt.

Adding columns to an append-only table is safe: the trigger refuses UPDATE and
DELETE of *rows*, and ALTER TABLE is neither. Existing rows get NULL for the
service columns and an empty list for the stages, which is honest — they were
written before services existed, and a backfilled "probably Support" would be
a guess sitting in the same column as measurements.

Revision ID: 9d4e1f7a2c85
Revises: 8c3d9a4e7b21
Create Date: 2026-08-01 10:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision: str = "9d4e1f7a2c85"
down_revision: str | None = "8c3d9a4e7b21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # No foreign key on the service, deliberately — the same reasoning as
    # `selected_queue_id`. A decision is evidence, not a live reference, and
    # must survive the service being archived.
    op.add_column("routing_decisions", sa.Column("selected_service_id", GUID(), nullable=True))
    op.add_column(
        "routing_decisions", sa.Column("selected_service_name", sa.String(255), nullable=True)
    )
    op.add_column("routing_decisions", sa.Column("service_version", sa.Integer(), nullable=True))
    op.add_column(
        "routing_decisions",
        sa.Column("resolution_stages", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("routing_decisions", "resolution_stages")
    op.drop_column("routing_decisions", "service_version")
    op.drop_column("routing_decisions", "selected_service_name")
    op.drop_column("routing_decisions", "selected_service_id")
