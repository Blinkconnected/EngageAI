"""ORM entities for the M24 ERPNext integration. See
``docs/architecture/erp-integration.md``.

``ErpConfig`` mirrors ``ChannelConfig`` exactly (encrypted credentials via
the same ``EncryptedJSON`` type, soft-deletable) — ERPNext credentials
are as sensitive and as per-company as any channel's. ``ErpCustomerLink``
maps one BlinkEngage ``Customer`` to the ERPNext Customer document created
for it (outbound sync). ``ErpSyncedRecord`` is a single generic cache
table for every inbound document type (invoices, sales orders,
quotations, support tickets, payments, contacts) rather than one table
per type — these are heterogeneous, read-only, per-company-customized
document shapes only ever displayed, never queried/filtered relationally
beyond "this customer's records of doctype X," so one JSON-payload table
with a ``doctype`` discriminator avoids six near-duplicate tables for no
real query benefit.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from blinkengage.infrastructure.database.encrypted_json import EncryptedJSON


class ErpConfig(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "erp_configs"

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    credentials: Mapped[dict[str, Any]] = mapped_column(
        EncryptedJSON(), nullable=False, default=dict
    )
    webhook_secret: Mapped[str | None] = mapped_column(String(255), default=None)


class ErpCustomerLink(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "erp_customer_links"
    __table_args__ = (UniqueConstraint("customer_id", name="uq_erp_customer_links_customer"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    erp_customer_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ErpSyncedRecord(UUIDPrimaryKeyMixin, Base):
    """Append/update-in-place cache of an ERPNext document, refreshed by
    either the inbound webhook or a manual pull. No ``SoftDeleteMixin`` —
    if ERPNext no longer reports a record, the last-known snapshot simply
    stops being refreshed rather than being tracked as "deleted" (this
    integration never deletes ERPNext's own data)."""

    __tablename__ = "erp_synced_records"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "doctype", "external_name", name="uq_erp_synced_records_key"
        ),
        Index("ix_erp_synced_records_customer", "customer_id", "doctype"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("customers.id", ondelete="SET NULL"), default=None
    )
    doctype: Mapped[str] = mapped_column(String(100), nullable=False)
    external_name: Mapped[str] = mapped_column(String(255), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    external_modified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
