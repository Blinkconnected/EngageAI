"""Knowledge documents: extracted attachment text

Revision ID: b7e3d51a9c46
Revises: a4f1c92b3e57
Create Date: 2026-08-13 19:05:00.000000

See ``docs/architecture/company-ai-brain.md`` (Phase 4C).

One table. Attachments arriving at a knowledge mailbox are read for their text
and nothing else — no model sees them in this phase, and no knowledge record is
written from them.

**Refusals are rows.** ``status`` is ``EXTRACTED`` or ``REJECTED``, and the
rejected row is the more useful of the two: "your Q3 price list arrived and is
a scan we cannot read" is answerable, and silence is not. That is why the
rejection reason and detail are columns rather than log lines.

**Deduplicated on content, per company.** The same PDF forwarded three times is
one document; re-parsing identical bytes to reach an identical answer is work
nobody asked for. Company-scoped because two tenants sending the same public
price list are two documents, and a global key would let one suppress the
other's.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID, UtcDateTime

revision: str = "b7e3d51a9c46"
down_revision: str | Sequence[str] | None = "a4f1c92b3e57"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_documents",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "company_id",
            GUID(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_message_id",
            GUID(),
            sa.ForeignKey("knowledge_source_messages.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("detected_kind", sa.String(length=16), nullable=True),
        sa.Column("declared_content_type", sa.String(length=200), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("rejection_reason", sa.String(length=40), nullable=True),
        sa.Column("rejection_detail", sa.Text(), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("parser", sa.String(length=40), nullable=True),
        sa.Column("parser_version", sa.String(length=40), nullable=True),
        sa.Column("units_read", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.Column("updated_at", UtcDateTime(), nullable=False),
        sa.UniqueConstraint("company_id", "content_hash", name="uq_knowledge_documents_content"),
    )
    op.create_index("ix_knowledge_documents_company_id", "knowledge_documents", ["company_id"])
    op.create_index(
        "ix_knowledge_documents_source_message_id",
        "knowledge_documents",
        ["source_message_id"],
    )
    op.create_index(
        "ix_knowledge_documents_company_status",
        "knowledge_documents",
        ["company_id", "status"],
    )


def downgrade() -> None:
    for index in (
        "ix_knowledge_documents_company_status",
        "ix_knowledge_documents_source_message_id",
        "ix_knowledge_documents_company_id",
    ):
        op.drop_index(index, table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
