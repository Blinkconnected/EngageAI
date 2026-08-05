"""Learning Platform, phase 2: clusters, trends and anomalies.

Everything here is **derived and rebuildable** from the observations
phase 1 already stores. That is what makes the downgrade safe to run
against production: dropping these four tables loses an interpretation,
not a record, and the next sweep rebuilds it.

Revision ID: f6c3d95a2e81
Revises: e5b2c83f19d7
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision: str = "f6c3d95a2e81"
down_revision: str | None = "e5b2c83f19d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "learning_clusters",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "company_id",
            GUID(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("signature", sa.String(64), nullable=False),
        sa.Column("algorithm_version", sa.Integer(), nullable=False),
        sa.Column("pipeline_version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="forming"),
        sa.Column(
            "merged_into_id",
            GUID(),
            sa.ForeignKey("learning_clusters.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("centroid", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("centroid_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("feature_summary", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("language_distribution", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("distinct_customers", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("distinct_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False, server_default="0"),
        sa.Column("stability", sa.Numeric(5, 4), nullable=False, server_default="0"),
        sa.Column("meets_floors", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        # The deduplication constraint. A cluster's identity is its
        # centroid signature, so a replay that rediscovers the same shape
        # collides with itself instead of writing a second row.
        sa.UniqueConstraint(
            "company_id",
            "algorithm_version",
            "signature",
            name="uq_learning_clusters_signature",
        ),
    )
    op.create_index("ix_learning_clusters_company_id", "learning_clusters", ["company_id"])
    op.create_index(
        "ix_learning_clusters_company_state",
        "learning_clusters",
        ["company_id", "state", "last_seen"],
    )
    op.create_index(
        "ix_learning_clusters_company_confidence",
        "learning_clusters",
        ["company_id", "confidence"],
    )

    op.create_table(
        "learning_cluster_members",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "company_id",
            GUID(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "cluster_id",
            GUID(),
            sa.ForeignKey("learning_clusters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "observation_id",
            GUID(),
            sa.ForeignKey("learning_observations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("similarity", sa.Numeric(5, 4), nullable=False, server_default="0"),
        sa.UniqueConstraint(
            "cluster_id", "observation_id", name="uq_learning_cluster_members_pair"
        ),
    )
    op.create_index(
        "ix_learning_cluster_members_company_id", "learning_cluster_members", ["company_id"]
    )
    op.create_index(
        "ix_learning_cluster_members_observation",
        "learning_cluster_members",
        ["company_id", "observation_id"],
    )
    op.create_index(
        "ix_learning_cluster_members_cluster",
        "learning_cluster_members",
        ["cluster_id", "observed_at"],
    )

    op.create_table(
        "learning_trends",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "company_id",
            GUID(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("subject_kind", sa.String(16), nullable=False),
        sa.Column("subject_key", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        # Both stored: the p-value is what the test said, the q-value is
        # what it means once the rest of the family is accounted for.
        sa.Column("p_value", sa.Numeric(12, 10), nullable=False),
        sa.Column("q_value", sa.Numeric(12, 10), nullable=False),
        sa.Column("recent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("baseline_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rate_ratio", sa.Numeric(10, 4), nullable=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_days", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("windows_held", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("provisional", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "company_id",
            "subject_kind",
            "subject_key",
            "kind",
            "window_end",
            name="uq_learning_trends_window",
        ),
    )
    op.create_index("ix_learning_trends_company_id", "learning_trends", ["company_id"])
    op.create_index(
        "ix_learning_trends_company_detected", "learning_trends", ["company_id", "detected_at"]
    )
    op.create_index(
        "ix_learning_trends_company_kind",
        "learning_trends",
        ["company_id", "kind", "provisional"],
    )

    op.create_table(
        "learning_anomalies",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "company_id",
            GUID(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("subject_key", sa.String(128), nullable=False),
        sa.Column(
            "cluster_id",
            GUID(),
            sa.ForeignKey("learning_clusters.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("severity", sa.String(8), nullable=False, server_default="low"),
        sa.Column("observed", sa.Numeric(14, 4), nullable=False),
        sa.Column("baseline", sa.Numeric(14, 4), nullable=False),
        sa.Column("score", sa.Numeric(14, 4), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "company_id", "kind", "subject_key", "window_end", name="uq_learning_anomalies_window"
        ),
    )
    op.create_index("ix_learning_anomalies_company_id", "learning_anomalies", ["company_id"])
    op.create_index(
        "ix_learning_anomalies_company_detected",
        "learning_anomalies",
        ["company_id", "detected_at"],
    )
    op.create_index(
        "ix_learning_anomalies_company_severity",
        "learning_anomalies",
        ["company_id", "severity", "detected_at"],
    )


def downgrade() -> None:
    # Children first: members reference clusters, anomalies reference
    # them nullably. Dropping in creation order would leave PostgreSQL
    # refusing on the foreign keys.
    op.drop_table("learning_anomalies")
    op.drop_table("learning_trends")
    op.drop_table("learning_cluster_members")
    op.drop_table("learning_clusters")
