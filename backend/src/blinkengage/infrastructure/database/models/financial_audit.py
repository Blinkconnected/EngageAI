"""The immutable financial audit trail.

One table, append-only, and deliberately **denormalized**: an audit row
carries the actor's email and name as values rather than only a foreign
key, and the amounts as text-safe numerics rather than joins to the
documents. An investigation that requires five other tables to still
hold their original values is not an audit trail — it is a query that
happens to work today.

On PostgreSQL a trigger rejects UPDATE and DELETE outright, so
"immutable" survives a ``psql`` session and not only repository
discipline.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.domain.money import PRICE_PRECISION, PRICE_SCALE
from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    UtcDateTime,
    UUIDPrimaryKeyMixin,
)


class FinancialAuditEvent(UUIDPrimaryKeyMixin, Base):
    """One thing that happened to a financial document."""

    __tablename__ = "financial_audit_events"
    __table_args__ = (
        # The three ways an investigation starts: from a document, from
        # a company's history, or from "what else happened when this
        # did".
        Index("ix_financial_audit_entity", "entity_type", "entity_id", "occurred_at"),
        Index("ix_financial_audit_company", "company_id", "occurred_at"),
        Index("ix_financial_audit_correlation", "correlation_id"),
    )

    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)

    #: SET NULL rather than CASCADE, and never a hard dependency: an
    #: audit row must outlive the company it describes, or deleting a
    #: customer would erase the record of what they were charged.
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="SET NULL"), default=None
    )

    #: Both states, always. "It became PAID" does not say whether it was
    #: issued or overdue beforehand, and that is exactly what a dispute
    #: turns on. NULL previous_state means the document did not exist.
    previous_state: Mapped[str | None] = mapped_column(String(30), default=None)
    new_state: Mapped[str | None] = mapped_column(String(30), default=None)

    #: The amount this event moved, where it moved one. Stored on the
    #: event rather than derived from the document, because the document
    #: has since moved on.
    amount: Mapped[Decimal | None] = mapped_column(
        Numeric(PRICE_PRECISION, PRICE_SCALE), default=None
    )
    currency: Mapped[str | None] = mapped_column(String(3), default=None)

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    #: Denormalized deliberately. A SET NULL foreign key turns every
    #: action an ex-employee took into an anonymous one, and "who did
    #: this" is the second question every investigation asks.
    actor_email: Mapped[str | None] = mapped_column(String(255), default=None)
    actor_name: Mapped[str | None] = mapped_column(String(255), default=None)
    #: True when the system acted — a scheduled sweep, a webhook. A real
    #: and distinct answer from "we don't know who", which is what a
    #: bare NULL actor would otherwise imply.
    actor_is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    #: Ties every event produced by one logical action together. An
    #: allocation writes both a payment event and an invoice transition;
    #: without this they can only be matched by timestamp, which stops
    #: working the moment two operators act in the same second.
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)

    reason: Mapped[str | None] = mapped_column(Text, default=None)
    #: Event-specific extras — the document number, the counterpart id,
    #: the provider reference. A JSON blob rather than a column per
    #: variant, since these differ per event type and none is queried
    #: relationally.
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    occurred_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), server_default=func.now(), nullable=False
    )
