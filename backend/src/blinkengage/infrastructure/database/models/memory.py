"""Memory Platform storage: ``MemoryFact``, ``MemoryEvidence``,
``MemoryConfidenceSample``.

See ``docs/architecture/memory-platform.md``.

**One table for three tiers, not three tables.** Organizational, Customer
and Experience memory share the entire contract — subject, evidence,
confidence, lifecycle, steward, human state — and differ only in their
fact-type vocabulary and in what their subject is. Three tables would mean
three repositories, three copies of the decay and lifecycle code, and
three migrations every time the contract grows.

The decisive argument is erasure. A customer erasure request must remove
that customer's facts *and* weaken the aggregate facts their conversations
supported, in one transaction. Across three tables that becomes a
multi-table dance where a missed table is a compliance failure that looks
like nothing; against one table it is one delete and one recompute.

Tier-specific shape lives in ``attributes`` (portable ``JSON``, not
``JSONB`` — this codebase's SQLite-compatibility rule) carrying its own
``attributes_schema_version``, which is what makes the payload evolvable
without a migration per fact type.
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


class MemoryFact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One remembered observation.

    **Not soft-deleted.** Every other entity in this schema uses
    ``SoftDeleteMixin`` so rows survive for the audit trail, and that is
    exactly wrong here: this table is subject to erasure requests, and a
    store that promised both immutability and deletion would be promising
    one of them falsely. Decay archives; erasure deletes. The two are
    different operations with different audit records, and the schema has
    to be able to honour the second.
    """

    __tablename__ = "memory_facts"
    __table_args__ = (
        # The dedupe identity. A second observation of the same thing must
        # find the existing row and add evidence to it, not create a
        # sibling that splits the support between them — a fact observed a
        # hundred times across two rows crosses no threshold and is
        # believed less than one observed fifty times.
        UniqueConstraint(
            "company_id",
            "tier",
            "subject_type",
            "subject_id",
            "fact_type",
            "fact_key",
            name="uq_memory_facts_identity",
        ),
        # Reading one subject's memory: the Customer Timeline, the agent
        # sidebar, and the erasure query all take this path.
        Index("ix_memory_facts_subject", "company_id", "subject_type", "subject_id"),
        # Retrieval: one company, one tier, only what is retrievable.
        Index("ix_memory_facts_company_tier_state", "company_id", "tier", "lifecycle_state"),
        # The decay sweep claims by staleness. Partial, because the
        # overwhelming majority of rows are ACTIVE and already current —
        # the same shape as the outbox's `WHERE dispatched_at IS NULL`.
        Index(
            "ix_memory_facts_decay_due",
            "confidence_computed_at",
            postgresql_where=text("lifecycle_state <> 'purged'"),
            sqlite_where=text("lifecycle_state <> 'purged'"),
        ),
        # Promises coming due, and anything with an explicit expiry.
        Index(
            "ix_memory_facts_due",
            "company_id",
            "due_at",
            postgresql_where=text("due_at IS NOT NULL"),
            sqlite_where=text("due_at IS NOT NULL"),
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )

    tier: Mapped[str] = mapped_column(String(20), nullable=False)
    fact_type: Mapped[str] = mapped_column(String(48), nullable=False)
    #: Normalised dedupe key — see ``domain/memory_identity.py``. Never the
    #: statement text: a component that rewords its output between runs
    #: would otherwise fork the fact's history on every wording change.
    fact_key: Mapped[str] = mapped_column(String(200), nullable=False)

    # --- what the fact is about, which is the erasure key ---------------
    #
    # Polymorphic and therefore no foreign key: the subject may be a
    # company, a customer or an agent. Referential integrity is the
    # erasure service's job and is asserted by a test rather than by the
    # schema — the same trade already made for `embeddings.owner_id`.
    subject_type: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)

    statement: Mapped[str] = mapped_column(Text, nullable=False)
    attributes: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    #: Versioned per row, so the typed payload can evolve without a
    #: migration per fact type and a reader can tell what it is holding.
    attributes_schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    # --- belief ---------------------------------------------------------
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0"))
    confidence_computed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    confidence_state: Mapped[str] = mapped_column(String(16), nullable=False, default="observed")
    confidence_direction: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")

    # --- liveness -------------------------------------------------------
    lifecycle_state: Mapped[str] = mapped_column(String(16), nullable=False, default="active")

    # --- support --------------------------------------------------------
    #
    # Breadth is counted separately from volume because they mean different
    # things: forty repetitions by one agent is one habit, six agents
    # converging independently is a practice.
    support_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    distinct_customer_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    distinct_agent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    contradiction_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: 0–1 where measured; null where nothing measured it. Null is neutral
    #: in the confidence formula rather than bad — most conversations have
    #: no CSAT, and treating unmeasured as poor would let only the surveyed
    #: minority ever be believed.
    outcome_quality: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), default=None)
    #: Whether any evidence corroborates rather than merely repeats. Cached
    #: from the evidence rows because it gates the confidence ceiling and
    #: is read on every recompute.
    has_corroboration: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    # --- time -----------------------------------------------------------
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Corroborated by a human or a measured outcome — a strictly stronger
    #: thing than observed. If repetition counted as confirmation, a
    #: customer repeating a wrong belief would confirm it, which is the
    #: poisoning path arriving through a column name.
    last_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    # --- provenance and people -----------------------------------------
    created_from: Mapped[str] = mapped_column(String(24), nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    #: Where a contradiction or a review is routed. Deliberately separate
    #: from the subject: conflating "what this is about" with "who looks
    #: after it" is how an erasure request misses rows.
    steward_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    steward_role: Mapped[str | None] = mapped_column(String(64), default=None)

    human_state: Mapped[str] = mapped_column(String(16), nullable=False, default="unreviewed")
    human_state_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    human_state_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # --- optional dating ------------------------------------------------
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    #: Which pipeline produced it, so a bad extraction run can be found and
    #: rolled back rather than hunted for.
    pipeline_version: Mapped[str | None] = mapped_column(String(64), default=None)

    #: How many times recomputing this fact has failed. A circuit breaker,
    #: not a silent drop: a fact at the cap stops being claimed and stays
    #: visible for an operator, so one poison row cannot be reclaimed on
    #: every sweep forever while healthy rows behind it are never reached.
    #: The knowledge index sweep already carries this guard, added after
    #: the relay-starvation incident; the decay sweep shipped without it.
    recompute_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    recompute_error: Mapped[str | None] = mapped_column(Text, default=None)

    evidence: Mapped[list["MemoryEvidence"]] = relationship(
        back_populates="fact", cascade="all, delete-orphan"
    )


class MemoryEvidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Why a fact is believed. **Pointers, never copies.**

    Storing a conversation excerpt here would put customer content into a
    second store with different retention and a different permission —
    precisely the leak the audit consumer's redaction list already exists
    to close — and it would turn erasure from a row deletion into a
    text-editing problem.

    ``customer_id`` and ``agent_id`` are denormalised onto the row rather
    than resolved through ``conversation_id`` later. Two reasons, both
    load-bearing: the distinct-customer and distinct-agent counters are
    what stop one person's habit becoming company policy, and erasure joins
    on ``customer_id`` — resolving it lazily would make erasure depend on
    the conversation row still existing, which after a conversation purge
    it does not.
    """

    __tablename__ = "memory_evidence"
    __table_args__ = (
        # Re-observing the same source must be idempotent. Without this, a
        # consumer replaying a batch inflates exactly the counters
        # confidence is computed from — and at-least-once delivery makes
        # replay the normal case, not the exceptional one.
        UniqueConstraint("fact_id", "source_type", "source_id", name="uq_memory_evidence_source"),
        Index("ix_memory_evidence_fact", "fact_id"),
        # The erasure path.
        Index("ix_memory_evidence_customer", "company_id", "customer_id"),
        Index("ix_memory_evidence_conversation", "company_id", "conversation_id"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fact_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("memory_facts.id", ondelete="CASCADE"), nullable=False
    )

    source_type: Mapped[str] = mapped_column(String(24), nullable=False)
    #: Nullable: an import or a system record may have no id in this
    #: platform. The unique constraint tolerates it because a null source
    #: id with a given type is at most one row per fact in practice.
    source_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), default=None)

    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("conversations.id", ondelete="CASCADE"), default=None
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("customers.id", ondelete="CASCADE"), default=None
    )
    #: ``SET NULL``, unlike the two above: an agent leaving must not delete
    #: the evidence that a practice worked. The person is detached; the
    #: observation stands.
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("agents.id", ondelete="SET NULL"), default=None
    )

    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    weight: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("1"))

    fact: Mapped["MemoryFact"] = relationship(back_populates="evidence")


class MemoryContradiction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One thing that disagrees with a fact.

    **Rows, not a counter.** ``contradiction_count`` was an increment, and
    an increment is wrong for exactly the reason this codebase already
    documents about evidence: it cannot be replayed. Contradiction enters
    the confidence function as a negative term, so a redelivered
    ``ContradictionDetected`` demoted a true fact on no new information —
    and at-least-once delivery makes redelivery routine, not exceptional.

    The shape is deliberately the same as ``memory_evidence``: a
    uniqueness constraint on the source, and the count recomputed from the
    rows rather than tracked alongside them. Two tables, one rule — every
    input to confidence is a ``COUNT`` over rows protected by a unique
    constraint.
    """

    __tablename__ = "memory_contradictions"
    __table_args__ = (
        UniqueConstraint(
            "fact_id", "source_type", "source_id", name="uq_memory_contradictions_source"
        ),
        Index("ix_memory_contradictions_fact", "fact_id"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fact_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("memory_facts.id", ondelete="CASCADE"), nullable=False
    )
    #: What disagreed — a published article, a system of record, a human.
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), default=None)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), default=None)


class MemoryConfidenceSample(UUIDPrimaryKeyMixin, Base):
    """One recomputation of a fact's confidence.

    Append-only and pruned on a rolling window — no ``TimestampMixin``,
    same philosophy as ``AuditLog`` and ``EventOutbox``: the row *is* the
    timestamped record, so a second updated_at would be noise.

    It exists for two reasons. ``confidence_direction`` is computed from
    the evidence deltas here rather than by differencing the confidence
    column, because confidence includes recency decay and differencing it
    would report FALLING for every fact that is merely quiet. And it is
    what answers *"why is this 0.31 now when it was 0.88 in March?"* with a
    curve instead of a shrug.
    """

    __tablename__ = "memory_confidence_samples"
    __table_args__ = (
        Index("ix_memory_confidence_samples_fact", "fact_id", "computed_at"),
        Index("ix_memory_confidence_samples_pruning", "computed_at"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fact_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("memory_facts.id", ondelete="CASCADE"), nullable=False
    )
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    #: The **running totals** at the moment of the sample. Deltas are
    #: derived by subtracting the previous sample's totals.
    #:
    #: The first version of this table stored only the deltas, and the
    #: delta was then computed as `current_total - previous_delta` —
    #: a total minus a delta, which is dimensionally meaningless and
    #: drifted upward as soon as support grew by more than one between
    #: sweeps. Totals are self-describing and a delta derived from two of
    #: them cannot drift.
    support_total: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    contradiction_total: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    #: Movement **across the direction window**, not since the previous
    #: sample: ``total - oldest_total_in_window``. A sample is written on
    #: every mutation, so a per-step delta would only ever show whichever
    #: single dimension the last write touched — and `CONTESTED`, which
    #: needs both moving, could never be observed. Derived from the
    #: totals above, which remain the source of truth.
    supporting_delta: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    contradicting_delta: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


#: ``Embedding.owner_type`` for a memory fact, so stage 1's polymorphic
#: embeddings table can carry memory vectors when semantic recall over
#: memory arrives. Declared here rather than there because this is the
#: module that owns what a memory fact is.
OWNER_MEMORY_FACT = "MEMORY_FACT"


__all__ = [
    "OWNER_MEMORY_FACT",
    "MemoryConfidenceSample",
    "MemoryContradiction",
    "MemoryEvidence",
    "MemoryFact",
]
