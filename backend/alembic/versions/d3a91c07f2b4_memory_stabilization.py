"""Stabilization: contradictions become rows, samples carry totals, and the
decay sweep gains a circuit breaker.

The architecture freeze review found four live defects in the Memory
Platform whose common shape is *a number that was tracked instead of
derived*. This migration provides the storage those numbers are derived
from.

``memory_contradictions`` replaces the ``contradiction_count`` increment.
An increment cannot be replayed, and contradiction is a negative term in
the confidence function, so a redelivered event demoted a true fact on no
new information — with at-least-once delivery making redelivery routine.
The table is shaped exactly like ``memory_evidence``: a uniqueness
constraint on the source, and the count recomputed from the rows. Two
tables, one rule — every input to confidence is a COUNT over rows
protected by a unique constraint.

``memory_confidence_samples`` gains **running totals**. It previously
stored only deltas, and the delta was computed as
``current_total - previous_delta`` — a total minus a delta, which is
dimensionally meaningless and drifts upward as soon as support grows by
more than one between sweeps. Totals are self-describing; a delta derived
from two of them cannot drift.

``memory_facts.recompute_attempts`` is the circuit breaker the decay sweep
shipped without. The knowledge index sweep already carries one, added
after the relay-starvation incident where the same hundred rows were
reclaimed and re-failed every five seconds for twenty hours while healthy
rows behind them were never claimed. The decay sweep had the same shape
and none of the guard.

**Backfill.** ``contradiction_count`` is not backfilled into the new
table: the counter recorded *how many times* something disagreed and never
*what* disagreed, so there is nothing to write rows from. Inventing a
source would be a guess presented as a record — the reasoning
``routing_decisions`` and the service directory already apply. Existing
counts are preserved on the column and the recompute takes over from the
rows, which means a fact contradicted before this migration keeps its
demotion until something contradicts it again. That is the honest
outcome; the alternative is fabricating provenance.

Revision ID: d3a91c07f2b4
Revises: c2f8a41b7e93
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision: str = "d3a91c07f2b4"
down_revision: str | Sequence[str] | None = "c2f8a41b7e93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_contradictions",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "company_id",
            GUID(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "fact_id",
            GUID(),
            sa.ForeignKey("memory_facts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", GUID(), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        # The whole point of the table: a redelivered contradiction is a
        # no-op rather than a second demotion.
        sa.UniqueConstraint(
            "fact_id", "source_type", "source_id", name="uq_memory_contradictions_source"
        ),
    )
    op.create_index(
        "ix_memory_contradictions_company_id", "memory_contradictions", ["company_id"]
    )
    op.create_index("ix_memory_contradictions_fact", "memory_contradictions", ["fact_id"])

    op.add_column(
        "memory_confidence_samples",
        sa.Column("support_total", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "memory_confidence_samples",
        sa.Column("contradiction_total", sa.Integer(), nullable=False, server_default="0"),
    )

    op.add_column(
        "memory_facts",
        sa.Column("recompute_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("memory_facts", sa.Column("recompute_error", sa.Text(), nullable=True))

    # Claiming is now tenant-fair: the sweep asks which companies have
    # stale facts before it asks which facts, so one enormous tenant
    # cannot own every batch. This index serves that first question.
    op.create_index(
        "ix_memory_facts_recompute_queue",
        "memory_facts",
        ["company_id", "confidence_computed_at"],
        postgresql_where=sa.text("lifecycle_state <> 'purged'"),
        sqlite_where=sa.text("lifecycle_state <> 'purged'"),
    )


def downgrade() -> None:
    op.drop_index("ix_memory_facts_recompute_queue", table_name="memory_facts")
    op.drop_column("memory_facts", "recompute_error")
    op.drop_column("memory_facts", "recompute_attempts")
    op.drop_column("memory_confidence_samples", "contradiction_total")
    op.drop_column("memory_confidence_samples", "support_total")
    op.drop_index("ix_memory_contradictions_fact", table_name="memory_contradictions")
    op.drop_index("ix_memory_contradictions_company_id", table_name="memory_contradictions")
    op.drop_table("memory_contradictions")
