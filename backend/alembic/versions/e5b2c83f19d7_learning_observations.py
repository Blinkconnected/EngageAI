"""Learning Platform, phase 1: observations and their evidence.

Stage 3 phase 1 — *observe only*. Nothing here clusters, detects, scores
or proposes; those are phases 2–4 and their tables are deliberately not
created. A table with no writer is a schema claim nothing honours.

Four tables:

``learning_observations`` is one unit of finished work. Unique on
``(source_id, pipeline_version)``, which is the entire idempotency story:
at-least-once delivery makes redelivery routine and a deliberate re-run is
a supported operation, so assembling the same source twice must find the
existing row rather than create a sibling that doubles every count derived
from it. Including the pipeline version in the key is what makes a bad
extractor *recoverable* — version 2 writes alongside version 1 rather than
over it, and the two can be compared before either is trusted.

``learning_observation_refs`` is the trace. **Pointers, never copies** —
an excerpt here would put customer content into a third store with its own
retention, which is the leak the audit log's redaction list already exists
to close, and would turn erasure from a row deletion into a text-editing
problem.

``learning_observation_features`` is what tiers 0 and 1 extracted, kept
apart from the observation because features are precisely what a pipeline
version bump changes — a re-extraction should rewrite them without
touching identity, provenance or outcome, none of which the extractor
decides.

``learning_runs`` records executions, unique per
``(company, run_type, pipeline_version, window_start)`` so a worker that
crashes mid-window and retries claims the same row instead of producing a
second set of results from one input.

**No soft delete anywhere**, matching Memory and for the same reason:
these rows are subject to erasure requests, and a store promising both
immutability and deletion promises one of them falsely.

**No backfill.** Learning starts the day it is switched on. Assembling a
year of history under a brand-new extractor is the worst possible input
to a system whose whole value is that its beliefs are traceable, and
inventing observations the platform never made would be a guess presented
as a record — the reasoning ``routing_decisions`` and the service
directory already apply.

Revision ID: e5b2c83f19d7
Revises: d3a91c07f2b4
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision: str = "e5b2c83f19d7"
down_revision: str | Sequence[str] | None = "d3a91c07f2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "learning_observations",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "company_id",
            GUID(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_kind", sa.String(length=24), nullable=False),
        sa.Column("source_id", GUID(), nullable=False),
        # Recorded for reporting and adapter debugging only. Nothing in
        # Learning may branch on it — the moment it does, adding voice or
        # email stops being an adapter change and becomes a redesign.
        sa.Column("channel", sa.String(length=32), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        # Nullable and no foreign key: an anonymous web-chat conversation
        # has no customer, which this platform already treats as normal.
        # Denormalised because *erasure joins on it*, and after a
        # conversation purge the join it would otherwise need is gone.
        sa.Column("customer_id", GUID(), nullable=True),
        sa.Column("pipeline_version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("exclusion_reason", sa.String(length=32), nullable=True),
        # Provenance: the anti-feedback-loop columns.
        sa.Column("human_authored_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ai_generated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ai_assisted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "human_authored_fraction", sa.Numeric(5, 4), nullable=False, server_default="0"
        ),
        # Outcome, copied from the single resolver rather than recomputed.
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("resolved_by", sa.String(length=16), nullable=False, server_default="unknown"),
        sa.Column(
            "outcome_attributable", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("reopened", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("escalated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "first_contact_resolution",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("handling_seconds", sa.Integer(), nullable=True),
        sa.Column("csat_score", sa.Integer(), nullable=True),
        sa.Column("outcome_quality", sa.Numeric(5, 4), nullable=True),
        sa.Column("settled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("settle_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extras", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "source_id", "pipeline_version", name="uq_learning_observations_source_version"
        ),
    )
    op.create_index("ix_learning_observations_company_id", "learning_observations", ["company_id"])
    op.create_index(
        "ix_learning_observations_company_state",
        "learning_observations",
        ["company_id", "state", "observed_at"],
    )
    op.create_index(
        "ix_learning_observations_customer",
        "learning_observations",
        ["company_id", "customer_id"],
    )
    # The settle sweep's queue. Partial, because most rows are settled and
    # the interesting query is for the ones that are not.
    op.create_index(
        "ix_learning_observations_pending",
        "learning_observations",
        ["company_id", "settle_due_at"],
        postgresql_where=sa.text("state = 'pending'"),
        sqlite_where=sa.text("state = 'pending'"),
    )

    op.create_table(
        "learning_observation_features",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "company_id",
            GUID(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "observation_id",
            GUID(),
            sa.ForeignKey("learning_observations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("topics", sa.JSON(), nullable=False),
        sa.Column("entities", sa.JSON(), nullable=False),
        sa.Column("inbound_turns", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("outbound_turns", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("human_char_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("observation_id", name="uq_learning_features_observation"),
    )
    op.create_index(
        "ix_learning_observation_features_company_id",
        "learning_observation_features",
        ["company_id"],
    )
    op.create_index(
        "ix_learning_features_company_language",
        "learning_observation_features",
        ["company_id", "language"],
    )

    op.create_table(
        "learning_observation_refs",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "company_id",
            GUID(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "observation_id",
            GUID(),
            sa.ForeignKey("learning_observations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ref_kind", sa.String(length=16), nullable=False),
        # Polymorphic, so no foreign key. Integrity is the erasure path's
        # job, asserted by a test — the same trade `embeddings.owner_id`
        # and `memory_facts.subject_id` already make.
        sa.Column("ref_id", GUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
        # Re-assembling the same observation must not duplicate its trace.
        sa.UniqueConstraint(
            "observation_id", "ref_kind", "ref_id", name="uq_learning_refs_target"
        ),
    )
    op.create_index(
        "ix_learning_observation_refs_company_id", "learning_observation_refs", ["company_id"]
    )
    op.create_index(
        "ix_learning_refs_observation", "learning_observation_refs", ["observation_id"]
    )

    op.create_table(
        "learning_runs",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "company_id",
            GUID(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("run_type", sa.String(length=32), nullable=False),
        sa.Column("pipeline_version", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="running"),
        sa.Column("items_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("items_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "company_id",
            "run_type",
            "pipeline_version",
            "window_start",
            name="uq_learning_runs_window",
        ),
    )
    op.create_index("ix_learning_runs_company_id", "learning_runs", ["company_id"])
    op.create_index(
        "ix_learning_runs_company_started", "learning_runs", ["company_id", "started_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_learning_runs_company_started", table_name="learning_runs")
    op.drop_index("ix_learning_runs_company_id", table_name="learning_runs")
    op.drop_table("learning_runs")

    op.drop_index("ix_learning_refs_observation", table_name="learning_observation_refs")
    op.drop_index(
        "ix_learning_observation_refs_company_id", table_name="learning_observation_refs"
    )
    op.drop_table("learning_observation_refs")

    op.drop_index(
        "ix_learning_features_company_language", table_name="learning_observation_features"
    )
    op.drop_index(
        "ix_learning_observation_features_company_id",
        table_name="learning_observation_features",
    )
    op.drop_table("learning_observation_features")

    op.drop_index("ix_learning_observations_pending", table_name="learning_observations")
    op.drop_index("ix_learning_observations_customer", table_name="learning_observations")
    op.drop_index("ix_learning_observations_company_state", table_name="learning_observations")
    op.drop_index("ix_learning_observations_company_id", table_name="learning_observations")
    op.drop_table("learning_observations")
