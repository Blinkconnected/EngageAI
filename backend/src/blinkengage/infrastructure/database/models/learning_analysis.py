"""Storage for what phase 2 discovers: clusters, trends, anomalies.

Stage 3, phase 2. Learning-owned, `company_id`-scoped, and — like every
table phase 1 added — **derived and rebuildable** from observations. That
property is what makes ``algorithm_version`` a real rollback boundary:
dropping every cluster and re-running loses nothing that cannot be
recomputed, so a bad clustering rule is recoverable rather than
permanent.

Separate module from ``learning.py`` because the two have different
rebuild costs and different lifetimes. Observations are expensive to
rebuild (they need the conversation history) and are the record;
clusters are cheap to rebuild and are an interpretation. Keeping them in
one file would invite a migration that treats them alike.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class LearningCluster(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A population of finished work that recurs.

    The unique constraint is the deduplication story, and it is on
    ``(company_id, algorithm_version, signature)`` rather than on an
    id: a signature is derived from the centroid, so the *same* cluster
    rediscovered by a later run — or by a replay — collides with itself
    and updates instead of duplicating. That is what makes "replay never
    creates a duplicate cluster" a property of the schema rather than a
    hope about the code.

    ``algorithm_version`` sits in the key for the same reason
    ``pipeline_version`` sits in the observation key: a rule change
    writes a parallel generation that can be compared against the old one
    before either is trusted.
    """

    __tablename__ = "learning_clusters"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "algorithm_version",
            "signature",
            name="uq_learning_clusters_signature",
        ),
        # The working set: one company's live clusters, biggest first.
        Index("ix_learning_clusters_company_state", "company_id", "state", "last_seen"),
        Index("ix_learning_clusters_company_confidence", "company_id", "confidence"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )

    #: Derived from the centroid — see ``domain.learning_cluster.signature``.
    #: Not a random id: two runs that find the same shape must agree that
    #: it is the same cluster.
    signature: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm_version: Mapped[int] = mapped_column(Integer, nullable=False)
    #: The observation pipeline version whose features this was built
    #: from. Clusters from different feature generations are not
    #: comparable and must never be mixed in one analysis.
    pipeline_version: Mapped[int] = mapped_column(Integer, nullable=False)

    state: Mapped[str] = mapped_column(String(16), nullable=False, default="forming")
    #: Where a merged cluster went, so a member's history stays traceable
    #: through the merge rather than dead-ending at a tombstone.
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("learning_clusters.id", ondelete="SET NULL"), default=None
    )

    #: The centroid, as ``term -> weight``. Portable ``JSON`` per this
    #: codebase's SQLite rule, not ``JSONB`` — and a lexical centroid
    #: rather than a vector, which is what keeps clustering reproducible
    #: across embedding-model changes.
    centroid: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False, default=dict)
    #: How many vectors the centroid is a mean of. Needed to keep it
    #: incremental: without the count a new member cannot be folded in
    #: without rebuilding from every member.
    centroid_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: What the cluster is *about*, for a human. Distinct from the
    #: centroid, which is tuned for comparison rather than for reading.
    feature_summary: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    #: ``language -> count``. Counts rather than fractions so two
    #: distributions can be summed on merge without tracking denominators.
    language_distribution: Mapped[dict[str, int]] = mapped_column(
        JSON, nullable=False, default=dict
    )

    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    distinct_customers: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    distinct_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: Computed from evidence, never asserted — the same rule memory
    #: confidence follows.
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0"))
    #: Jaccard overlap with the previous run's membership. A cluster still
    #: in motion is not one to propose from.
    stability: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0"))
    #: Floors are recorded, not just applied, so "why is this not a
    #: finding" is answerable from the row.
    meets_floors: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    members: Mapped[list[LearningClusterMember]] = relationship(
        back_populates="cluster", cascade="all, delete-orphan"
    )


class LearningClusterMember(UUIDPrimaryKeyMixin, Base):
    """One observation's membership of one cluster.

    Unique per ``(cluster_id, observation_id)``: the same observation
    cannot be counted twice in one cluster, which is what stops a replay
    or a merge inflating a size that everything downstream weighs.
    """

    __tablename__ = "learning_cluster_members"
    __table_args__ = (
        UniqueConstraint("cluster_id", "observation_id", name="uq_learning_cluster_members_pair"),
        Index("ix_learning_cluster_members_observation", "company_id", "observation_id"),
        Index("ix_learning_cluster_members_cluster", "cluster_id", "observed_at"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cluster_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("learning_clusters.id", ondelete="CASCADE"), nullable=False
    )
    observation_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("learning_observations.id", ondelete="CASCADE"), nullable=False
    )
    #: Denormalised from the observation so the membership timeline can be
    #: read without a join — and so it survives long enough to be useful
    #: while an erasure is removing the observation it points at.
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Cosine similarity to the centroid at the moment of joining. Kept
    #: because "why is this in here" is the first question anybody asks of
    #: a cluster they disagree with.
    similarity: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0"))

    cluster: Mapped[LearningCluster] = relationship(back_populates="members")


class LearningTrend(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A direction over time that survived correction and persistence.

    Unique per ``(company_id, subject_kind, subject_key, kind,
    window_end)`` so re-running an analysis over the same window updates
    its finding rather than filing it again. Re-analysis is routine — a
    worker restart, a manual run, a replay — and a trend list that grew a
    copy each time would be unreadable within a week.

    ``provisional`` is the persistence gate made visible: a finding that
    cleared the statistics once is stored, and is not a trend until a
    second consecutive window agrees.
    """

    __tablename__ = "learning_trends"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "subject_kind",
            "subject_key",
            "kind",
            "window_end",
            name="uq_learning_trends_window",
        ),
        Index("ix_learning_trends_company_detected", "company_id", "detected_at"),
        Index("ix_learning_trends_company_kind", "company_id", "kind", "provisional"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: ``cluster`` or ``topic``. Both are worth trending and they answer
    #: different questions: a topic trend crosses clusters, a cluster
    #: trend is about one recurring shape.
    subject_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)

    #: Both are stored. The p-value is what the test said; the q-value is
    #: what it means after the rest of the family was accounted for, and a
    #: reader needs to see that the correction happened.
    p_value: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    q_value: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)

    recent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    baseline_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rate_ratio: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), default=None)

    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    windows_held: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: Cleared the statistics, has not yet held for two windows.
    provisional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detail: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)


class LearningAnomaly(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One thing unlike its own history, in one window.

    Unique per ``(company_id, kind, subject_key, window_end)`` for the
    same reason trends are: an anomaly re-detected by a re-run is the same
    anomaly.

    **Nothing here is published.** No event, no notification. Charter
    phase 2 keeps anomalies as Learning-owned artefacts precisely so that
    their precision can be measured before anything is wired to them.
    """

    __tablename__ = "learning_anomalies"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "kind", "subject_key", "window_end", name="uq_learning_anomalies_window"
        ),
        Index("ix_learning_anomalies_company_detected", "company_id", "detected_at"),
        Index("ix_learning_anomalies_company_severity", "company_id", "severity", "detected_at"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    #: The cluster signature this is about. Not a foreign key: an anomaly
    #: outlives the cluster it describes, and a cluster that dissolves
    #: must not erase the record that it once behaved strangely.
    subject_key: Mapped[str] = mapped_column(String(128), nullable=False)
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("learning_clusters.id", ondelete="SET NULL"), default=None
    )

    severity: Mapped[str] = mapped_column(String(8), nullable=False, default="low")
    observed: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    baseline: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)

    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detail: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    #: Free text for the one line an operator reads first. Generated from
    #: the numbers, never from a model — phase 2 makes no model calls.
    summary: Mapped[str | None] = mapped_column(Text, default=None)


#: Run types recorded in ``learning_runs`` by phase 2's sweeps.
RUN_TYPE_CLUSTER = "cluster"
RUN_TYPE_ANALYSIS = "analysis"


__all__ = [
    "RUN_TYPE_ANALYSIS",
    "RUN_TYPE_CLUSTER",
    "LearningAnomaly",
    "LearningCluster",
    "LearningClusterMember",
    "LearningTrend",
]
