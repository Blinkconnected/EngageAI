"""What arrived, before anybody decided whether it was true.

Two tables, both company-scoped, neither of which the Brain reads to answer a
question. They exist so that a message which *may* become knowledge is durable,
attributable and exactly-once — and so the row that later cites a price can
point at the thing somebody actually sent.

``knowledge_source_messages`` is deliberately not ``messages``. A message row
belongs to a conversation and a customer, and manufacturing either from a price
list sent by the company's own finance team is the defect this whole branch
exists to prevent.
"""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    TimestampMixin,
    UtcDateTime,
    UUIDPrimaryKeyMixin,
)


class KnowledgeSourceMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One received message, stored once.

    **The unique constraint is the idempotency mechanism**, and it is the
    reason this table exists at all. The IMAP poll previously marked each
    message ``\\Seen`` as it read it and called that idempotency: a crash
    between the flag and any persistence lost the message permanently, with
    nothing anywhere recording that it had existed. Now the row is written
    first and ``\\Seen`` is an optimisation — redelivery hits the constraint
    and is recognised, not re-ingested.

    Application-level "does this exist?" cannot replace the constraint: two
    pollers running concurrently both read *no*, and both insert.
    """

    __tablename__ = "knowledge_source_messages"
    __table_args__ = (
        # Company first. The same Message-ID arriving at two companies'
        # mailboxes is two documents, and a globally-unique key would let one
        # company's ingestion silently suppress another's.
        UniqueConstraint(
            "company_id",
            "channel_config_id",
            "message_id",
            "content_hash",
            name="uq_knowledge_source_messages_identity",
        ),
        Index("ix_knowledge_source_messages_company_received", "company_id", "received_at"),
        Index("ix_knowledge_source_messages_company_status", "company_id", "status"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel_config_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("channel_configs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    #: RFC 5322 ``Message-ID``. Forgeable and occasionally reused, which is
    #: why it is half of the identity rather than all of it.
    message_id: Mapped[str] = mapped_column(String(998), nullable=False)
    #: SHA-256 of the raw bytes. The other half: it separates two genuinely
    #: different messages that share an id, and recognises a resend of the
    #: same one.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    sender: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    recipients: Mapped[str | None] = mapped_column(Text, default=None)
    subject: Mapped[str | None] = mapped_column(Text, default=None)
    received_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), default=None)

    #: Verbatim, as evidence. A price quoted from this must be reproducible in
    #: the form it arrived, so this is never rewritten — the readable
    #: flattening lives beside it rather than replacing it.
    raw_body: Mapped[str | None] = mapped_column(Text, default=None)
    #: HTML flattened for reading. Derived, replaceable, never authoritative.
    plain_body: Mapped[str | None] = mapped_column(Text, default=None)

    #: ``ACCEPTED`` or ``REJECTED``. A rejected message is still a row: an
    #: unauthorised sender who tried is exactly what an operator needs to see,
    #: and a rejection that leaves no trace is indistinguishable from mail
    #: that never arrived.
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    #: The ``RejectionReason`` value, when rejected. Internal — never returned
    #: to a sender, who would otherwise learn which condition to satisfy next.
    rejection_reason: Mapped[str | None] = mapped_column(String(40), default=None)

    #: Counted, not stored. Phase 4C is not authorized, so nothing here reads
    #: an attachment; knowing that a rejected message carried three of them is
    #: still worth having.
    attachment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: The ``authserv-id`` whose Authentication-Results were trusted, when any
    #: were. Null means no trusted verifier — which is a rejection, not a pass.
    authentication_authserv_id: Mapped[str | None] = mapped_column(String(255), default=None)
    authentication_summary: Mapped[str | None] = mapped_column(String(120), default=None)


class KnowledgeDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One attachment, and what could be read out of it.

    Immutable, and stored even when extraction failed. A refusal is the more
    useful row of the two: "we received your Q3 price list and could not read
    it because it is a scan" is answerable, and silence is not.

    Deduplicated on ``(company_id, content_hash)``. The same PDF forwarded
    three times is one document with three source messages pointing at it, and
    re-parsing identical bytes to reach an identical answer is work nobody
    asked for.
    """

    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint("company_id", "content_hash", name="uq_knowledge_documents_content"),
        Index("ix_knowledge_documents_company_status", "company_id", "status"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: The message it arrived on. Nullable because a later phase adds manual
    #: upload, which has no message.
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("knowledge_source_messages.id", ondelete="CASCADE"),
        default=None,
        index=True,
    )

    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    #: What the *bytes* are, sniffed. Never the declared content type, and
    #: never the extension: ``pricing.pdf`` containing a ZIP is a ZIP.
    detected_kind: Mapped[str | None] = mapped_column(String(16), default=None)
    #: What the sender claimed, kept only so the two can be compared.
    declared_content_type: Mapped[str | None] = mapped_column(String(200), default=None)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    #: Object-storage key, company-prefixed. Null when the document was
    #: refused before storage — an oversized file is not kept.
    storage_key: Mapped[str | None] = mapped_column(String(500), default=None)

    #: ``EXTRACTED`` or ``REJECTED``.
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    rejection_reason: Mapped[str | None] = mapped_column(String(40), default=None)
    rejection_detail: Mapped[str | None] = mapped_column(Text, default=None)

    extracted_text: Mapped[str | None] = mapped_column(Text, default=None)
    #: Which reader produced the text, and at what version. Extraction quality
    #: changes with the library, so a record citing this text has to be able
    #: to say what read it — otherwise "the document says 180" cannot be
    #: checked a year later when the same file extracts differently.
    parser: Mapped[str | None] = mapped_column(String(40), default=None)
    parser_version: Mapped[str | None] = mapped_column(String(40), default=None)
    #: Pages, sheets or rows read, and whether a cap stopped the read early —
    #: a truncation is otherwise invisible in the text.
    units_read: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    truncated: Mapped[bool] = mapped_column(nullable=False, default=False)


class KnowledgeSenderAllowlistEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An address a company has said may teach its Brain.

    Per address, never per domain. "Anyone at the company domain" is the rule
    that lets a spoofed CEO address and a departed employee both write pricing,
    and it is the specific thing this table exists to avoid.

    Starts empty for every company, deliberately. A knowledge mailbox that
    accepts nothing on its first day is the correct default; the alternative
    is a mailbox that trusts whoever finds it first.
    """

    __tablename__ = "knowledge_sender_allowlist"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "normalized_email", name="uq_knowledge_sender_allowlist_address"
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: As typed, for display.
    email_address: Mapped[str] = mapped_column(String(320), nullable=False)
    #: Case-folded, for comparison. Written by ``normalise_address`` so the
    #: stored form and the lookup form cannot drift apart.
    normalized_email: Mapped[str] = mapped_column(String(320), nullable=False)

    #: Disabled rather than deleted, so revoking access keeps the record that
    #: it was once granted — the question after an incident is always "who
    #: could have sent this, and when did that change".
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )


__all__ = [
    "KnowledgeDocument",
    "KnowledgeSenderAllowlistEntry",
    "KnowledgeSourceMessage",
]
