"""Structured knowledge ORM: ``KnowledgeRecord``.

See ``docs/architecture/company-knowledge-and-voice.md`` and
``domain/knowledge_records.py`` for why this is a table of its own rather
than a row in ``knowledge_articles`` or ``memory_facts``.

The short version: an article is prose found by resemblance, a memory fact
is evidential and decays, and a price is neither. It is a value found by
identity, true over a period, and authoritative because a human approved
the document it came from.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.domain.knowledge_records import (
    KnowledgeAccessLevel,
    KnowledgeLifecycleState,
    KnowledgeRecordType,
)
from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    TimestampMixin,
    UtcDateTime,
    UUIDPrimaryKeyMixin,
)


class KnowledgeRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One typed, deterministically queryable company fact.

    **No soft delete.** ``SoftDeleteMixin`` is deliberately absent: a
    withdrawn record is ``ARCHIVED`` and a replaced one is ``SUPERSEDED``,
    both of which stay readable forever. A price that was quoted must be
    reproducible in an audit two years later, and a ``deleted_at`` filter is
    exactly how it would stop being.
    """

    __tablename__ = "knowledge_records"
    __table_args__ = (
        # The resolution query: one company's active records for a subject,
        # narrowed by period. Ordered so the leading columns are the ones
        # every lookup fixes, with the period column last because it is a
        # range scan.
        Index(
            "ix_knowledge_records_resolution",
            "company_id",
            "record_type",
            "subject_key",
            "effective_from",
        ),
        # The version chain, walked when showing history.
        Index("ix_knowledge_records_chain", "company_id", "subject_key", "version"),
        # The admin list: what is live right now.
        Index(
            "ix_knowledge_records_company_state",
            "company_id",
            "lifecycle_state",
        ),
        # One version number per subject per type per company. The overlap
        # rule (no two ACTIVE records sharing an instant) cannot be expressed
        # as a portable constraint — PostgreSQL could do it with an exclusion
        # constraint over a tstzrange, SQLite cannot — so it is enforced in
        # the service inside the write transaction and asserted by tests.
        # This one *is* portable, and it stops the chain forking.
        UniqueConstraint(
            "company_id",
            "record_type",
            "subject_key",
            "version",
            name="uq_knowledge_records_subject_version",
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )

    record_type: Mapped[KnowledgeRecordType] = mapped_column(String(32), nullable=False)

    #: Canonical, deterministic identity — see
    #: ``domain.knowledge_records.canonical_subject_key``. Never derived by a
    #: model, never dependent on stored state.
    subject_key: Mapped[str] = mapped_column(String(200), nullable=False)
    #: The authored form, for display. ``subject_key`` is for lookup.
    subject_label: Mapped[str] = mapped_column(String(300), nullable=False)

    #: Portable ``JSON``, not ``JSONB`` — this codebase's SQLite rule. Shape
    #: is validated against the per-type schema in the domain before it ever
    #: reaches here, and unknown keys are rejected rather than stored.
    attributes: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    attributes_schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1"), default=1
    )

    #: Half-open: ``effective_from <= t < effective_until``. ``NULL`` until
    #: means open-ended, rather than a sentinel far-future date somebody
    #: eventually compares against and gets wrong.
    effective_from: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    effective_until: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)

    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        # RESTRICT, not CASCADE: the chain is the audit trail, and deleting
        # a link would silently orphan every version after it. Nothing
        # deletes these rows anyway — this stops a future migration doing it
        # by accident.
        ForeignKey("knowledge_records.id", ondelete="RESTRICT"),
        nullable=True,
    )
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("knowledge_records.id", ondelete="RESTRICT"), nullable=True
    )

    lifecycle_state: Mapped[KnowledgeLifecycleState] = mapped_column(
        String(16),
        nullable=False,
        server_default=text(f"'{KnowledgeLifecycleState.DRAFT.value}'"),
    )
    access_level: Mapped[KnowledgeAccessLevel] = mapped_column(
        String(16),
        nullable=False,
        server_default=text(f"'{KnowledgeAccessLevel.PUBLIC_TO_AI.value}'"),
    )

    #: Reuses ``domain.memory.CreatedFrom`` values rather than defining a
    #: parallel vocabulary — "how did this come to exist" is the same
    #: question here as it is for a memory fact, and two enums answering it
    #: differently is two that drift.
    created_from: Mapped[str] = mapped_column(String(24), nullable=False)

    #: Where this came from. One of the two must be present to publish;
    #: ``source_document_version_id`` stays nullable and un-constrained until
    #: M2D introduces the documents table it will point at. Adding the FK
    #: then is a migration; inventing the table now to satisfy a column would
    #: be building M2D early.
    source_document_version_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    source_reference: Mapped[str | None] = mapped_column(Text, nullable=True)

    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<KnowledgeRecord {self.record_type} {self.subject_key} "
            f"v{self.version} {self.lifecycle_state}>"
        )
