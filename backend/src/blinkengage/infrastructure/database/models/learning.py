"""Learning Platform storage — phase 1.

See [the charter](../../../../../../docs/architecture/learning-platform-charter.md).

Three tables, and only three. The charter names nine that Learning will
eventually own; ``clusters``, ``cluster_members``, ``candidates``,
``suppressions``, ``trends`` and ``gaps`` belong to phases 2–4 and are not
created here. A table with no writer is a schema claim nothing honours,
and this codebase already treats speculative structure as a defect.

**Everything here is derived and rebuildable** from source events. That is
not a nice property, it is the one that makes ``pipeline_version``
rollback real: a bad extractor is corrected by bumping the version and
replaying, with both generations present and comparable rather than one
silently overwritten.

**No soft delete**, for the same reason as Memory: these rows are subject
to erasure requests, and a store promising both immutability and deletion
promises one of them falsely.
"""

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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class LearningObservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One unit of finished work, as Learning saw it.

    The unique constraint is the whole idempotency story. At-least-once
    delivery makes redelivery routine, a consumer restart replays, and a
    deliberate re-run is a supported operation — so assembling the same
    source twice under the same pipeline version must find the existing
    row rather than create a sibling. Two rows for one conversation would
    double every count derived from them.

    Including ``pipeline_version`` in the key is what makes a bad
    extraction *recoverable*: version 2 writes alongside version 1 instead
    of over it, and the two can be compared before either is trusted.
    """

    __tablename__ = "learning_observations"
    __table_args__ = (
        UniqueConstraint(
            "source_id", "pipeline_version", name="uq_learning_observations_source_version"
        ),
        # The eligibility scan: one company, ready rows only. Partial,
        # because most rows are READY and the interesting query is for the
        # ones that are not.
        Index(
            "ix_learning_observations_pending",
            "company_id",
            "settle_due_at",
            postgresql_where=text("state = 'pending'"),
            sqlite_where=text("state = 'pending'"),
        ),
        Index("ix_learning_observations_company_state", "company_id", "state", "observed_at"),
        # Erasure joins on this.
        Index("ix_learning_observations_customer", "company_id", "customer_id"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )

    source_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    #: Recorded for reporting and adapter debugging only. **Nothing in
    #: Learning may branch on it** — the moment it does, adding voice or
    #: email stops being an adapter change.
    channel: Mapped[str | None] = mapped_column(String(32), default=None)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: Nullable and no foreign key: an anonymous web-chat conversation has
    #: no customer, which is a normal case this platform already treats as
    #: normal. Denormalised here rather than resolved through the source
    #: later because **erasure joins on it**, and after a conversation
    #: purge the join it would otherwise need is gone.
    customer_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), default=None)

    pipeline_version: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    exclusion_reason: Mapped[str | None] = mapped_column(String(32), default=None)

    # --- provenance: the anti-feedback-loop columns --------------------
    human_authored_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ai_generated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ai_assisted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Cached so the health dashboard can aggregate it without recomputing
    #: per row. The feedback ratio is the number that says whether the
    #: platform is learning from the world or from itself.
    human_authored_fraction: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, default=Decimal("0")
    )

    # --- outcome, from the single resolver ------------------------------
    #
    # Copied from ``domain.conversation_outcome.derive`` rather than
    # recomputed. Two definitions of "resolved" is the A3 defect that
    # produced zero SLA clocks platform-wide.
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolved_by: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    #: Whether this outcome is evidence that something *worked*. False for
    #: workflow, timeout and AI closures — a rule firing is not a person
    #: judging a conversation finished.
    outcome_attributable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reopened: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    escalated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    first_contact_resolution: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    handling_seconds: Mapped[int | None] = mapped_column(Integer, default=None)
    csat_score: Mapped[int | None] = mapped_column(Integer, default=None)
    #: ``None`` where nothing measured it — never zero. Most conversations
    #: have no CSAT, and treating unmeasured as bad would let only the
    #: surveyed minority ever be believed.
    outcome_quality: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), default=None)
    settled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: When the settle window closes. The sweep promotes PENDING → READY
    #: from this; without it, clustering would consume conversations whose
    #: CSAT had not landed.
    settle_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    #: Present for reporting and future stratification. Nothing in phase 1
    #: reads them, and they are cheap to record now and expensive to
    #: backfill later.
    extras: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)

    features: Mapped["LearningObservationFeature | None"] = relationship(
        back_populates="observation", cascade="all, delete-orphan", uselist=False
    )
    content_refs: Mapped[list["LearningObservationRef"]] = relationship(
        back_populates="observation", cascade="all, delete-orphan"
    )


class LearningObservationFeature(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """What tiers 0 and 1 extracted.

    A separate table rather than columns on the observation, because
    features are what a ``pipeline_version`` bump actually changes. Keeping
    them apart means a re-extraction rewrites one row and leaves the
    observation's identity, provenance and outcome — none of which the
    extractor decides — untouched.
    """

    __tablename__ = "learning_observation_features"
    __table_args__ = (
        UniqueConstraint("observation_id", name="uq_learning_features_observation"),
        Index("ix_learning_features_company_language", "company_id", "language"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    observation_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("learning_observations.id", ondelete="CASCADE"), nullable=False
    )

    #: ``ar`` / ``en`` / ``mixed`` / null. A script decision, honestly
    #: named — see ``domain/learning_features.detect_language``.
    language: Mapped[str | None] = mapped_column(String(16), default=None)
    #: Portable ``JSON`` per this codebase's SQLite rule, not ``JSONB``.
    topics: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    entities: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    inbound_turns: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outbound_turns: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    human_char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    observation: Mapped["LearningObservation"] = relationship(back_populates="features")


class LearningObservationRef(UUIDPrimaryKeyMixin, Base):
    """A pointer to what was observed. **Never a copy.**

    The charter requires every observation to be fully traceable to
    evidence, and this is the trace. Storing an excerpt instead would put
    customer content into a third store with its own retention — the leak
    the audit log's redaction list already exists to close — and turn
    erasure from a row deletion into a text-editing problem.

    No ``TimestampMixin``: the row is a pointer with an ordinal, and a
    created_at on a derived reference is noise.
    """

    __tablename__ = "learning_observation_refs"
    __table_args__ = (
        UniqueConstraint("observation_id", "ref_kind", "ref_id", name="uq_learning_refs_target"),
        Index("ix_learning_refs_observation", "observation_id"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    observation_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("learning_observations.id", ondelete="CASCADE"), nullable=False
    )
    ref_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    #: Polymorphic, so no foreign key. Integrity is the erasure path's job,
    #: asserted by a test — the same trade ``embeddings.owner_id`` and
    #: ``memory_facts.subject_id`` already make.
    ref_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    observation: Mapped["LearningObservation"] = relationship(back_populates="content_refs")


class LearningRun(UUIDPrimaryKeyMixin, Base):
    """One execution of a Learning job.

    Versioned and idempotent by ``(company, run_type, pipeline_version,
    window_start)``: a worker that crashes mid-window and retries claims
    the same row rather than producing a second set of results from the
    same input. Without it, a retry inflates exactly the counters that
    later become confidence.

    This is also where "is Learning healthy?" is answered from — the
    charter's §15 metrics are aggregates over these rows.
    """

    __tablename__ = "learning_runs"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "run_type",
            "pipeline_version",
            "window_start",
            name="uq_learning_runs_window",
        ),
        Index("ix_learning_runs_company_started", "company_id", "started_at"),
    )

    company_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), default=None, index=True
    )
    run_type: Mapped[str] = mapped_column(String(32), nullable=False)
    pipeline_version: Mapped[int] = mapped_column(Integer, nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")

    items_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_detail: Mapped[str | None] = mapped_column(Text, default=None)


#: Run types recorded in ``learning_runs.run_type``. Phase 1 has two.
RUN_TYPE_OBSERVATION = "observation"
RUN_TYPE_SETTLE = "settle"


__all__ = [
    "RUN_TYPE_OBSERVATION",
    "RUN_TYPE_SETTLE",
    "LearningObservation",
    "LearningObservationFeature",
    "LearningObservationRef",
    "LearningRun",
]
