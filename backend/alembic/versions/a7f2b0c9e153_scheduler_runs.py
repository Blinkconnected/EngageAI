"""scheduler runs: what each billing job actually did

See ``docs/architecture/billing.md``.

Billing runs unattended and every one of its jobs is idempotent, which is
exactly why it can fail for months without anybody noticing — a failed run
leaves its work for the next one and nothing looks wrong. Three of them did
precisely that, failing on roughly every other sweep, and the only evidence
was 132 stack traces in two days that nobody was reading.

One row per execution: when it started, how long it took, what it counted,
whether it failed. "When did the invoice run last succeed?" becomes a question
with an answer.

Not append-only, unlike the decision and ledger tables. The row is written when
the run *starts* and updated when it ends, because a run that started and never
finished is the most important thing this table can show — a worker killed
mid-execution leaves a ``RUNNING`` row that ages visibly, where recording only
on completion would leave nothing at all.

No backfill. The runs before this migration were not recorded and cannot be
reconstructed; a health page showing invented history would be worse than one
that honestly starts today.

Revision ID: a7f2b0c9e153
Revises: 9d4e1f7a2c85
Create Date: 2026-08-01 11:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision: str = "a7f2b0c9e153"
down_revision: str | None = "9d4e1f7a2c85"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scheduler_runs",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("task_name", sa.String(120), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        # Null while in flight — and still null afterwards if the worker
        # died, which is the signal a health page needs most.
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="RUNNING"),
        # A JSON bag rather than columns, so a new counter is a line in the
        # task instead of a migration.
        sa.Column("metrics", sa.JSON(), nullable=False, server_default="{}"),
        # Items the run could not process — counted separately from the run
        # failing outright, because a sweep that billed thirty companies and
        # could not bill one is a different problem.
        sa.Column("failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
    )
    # The only query that matters: "how is this task doing?", newest first.
    op.create_index("ix_scheduler_runs_task_recent", "scheduler_runs", ["task_name", "started_at"])


def downgrade() -> None:
    op.drop_index("ix_scheduler_runs_task_recent", table_name="scheduler_runs")
    op.drop_table("scheduler_runs")
