"""Customer ORM models: ``Customer``, ``Tag`` (company-scoped catalog), and
their ``CustomerTag`` join.

``custom_fields`` is a JSON bag for schema-less per-company attributes —
a full custom-field-*definition* system (with typed fields, validation,
admin-configurable schemas) is an Administration-feature concern for a
later milestone, not built here. Multi-channel identity resolution and
merge/dedupe (named in the roadmap for this entity) are deferred to
Phase 4, once the Channels/Conversations feature actually creates
per-channel contact records for a customer to resolve against — there's
nothing to resolve or merge until then.
"""

import uuid
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class Customer(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "customers"
    __table_args__ = (
        Index(
            "uq_customers_company_email",
            "company_id",
            "email",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        # M28 (see docs/architecture/performance.md): CustomerRepository
        # .list_for_company's non-search browse case sorts by full_name —
        # the single-column company_id index alone forces a separate sort
        # of every matching row before LIMIT, same issue as the
        # conversations list query fixed alongside this one.
        Index(
            "ix_customers_company_full_name",
            "company_id",
            "full_name",
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), default=None, index=True)
    phone: Mapped[str | None] = mapped_column(String(32), default=None, index=True)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    custom_fields: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    customer_tags: Mapped[list["CustomerTag"]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )


class Tag(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("company_id", "name", name="uq_tags_company_name"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)


class CustomerTag(Base):
    __tablename__ = "customer_tags"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("customers.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )

    customer: Mapped["Customer"] = relationship(back_populates="customer_tags")
    tag: Mapped["Tag"] = relationship()


class CustomerInternalRating(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A private, staff-only 1-5 star rating of a customer, with an
    optional note — never exposed on any customer-facing surface (the
    public CSAT survey flow is the unrelated, customer-submitted
    ``CsatResponse``/``csat_responses``; this is the reverse direction,
    staff rating the customer).

    Repeatable rather than a single mutable field on ``Customer``: an
    enterprise team wants a running history of "difficult customer" /
    "great customer" assessments from different agents/supervisors over
    time, not one value that silently overwrites the last person's
    judgment call.

    No ``SoftDeleteMixin`` — same reasoning as ``InternalNote``: a
    low-stakes internal annotation with no compliance requirement to
    retain a deleted row, durably recorded via the
    ``customer_internal_rating.deleted`` domain event regardless of the
    row's fate.
    """

    __tablename__ = "customer_internal_ratings"

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # SET NULL, not CASCADE — same reasoning as InternalNote.author_user_id:
    # a rating must outlive the user who gave it.
    rated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    # 1-5, validated at the API schema layer (Field(ge=1, le=5)) — same
    # convention as CsatResponse.rating, no DB check constraint either.
    stars: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, default=None)
