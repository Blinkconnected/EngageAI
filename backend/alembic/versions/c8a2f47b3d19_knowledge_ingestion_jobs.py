"""Knowledge ingestion jobs: a durable state machine for ingestion work

Revision ID: c8a2f47b3d19
Revises: b7e3d51a9c46
Create Date: 2026-08-13 21:30:00.000000

See ``docs/architecture/company-ai-brain.md`` (Phase 4D).

Ingestion was already durable in its *inputs* — the source message and the
document survive a crash. What did not survive was the knowledge that work had
been started and abandoned. This table is that fact.

**``job_key`` rather than a nullable composite unique key.** The natural
identity is ``(source_message, document)`` and ``document`` is nullable; SQL
treats NULLs as distinct, so a constraint over those columns would cheerfully
admit two message-level jobs for the same message. A deterministic string is
uniform across dialects and says what it means.

**Two indexes, two readers.** ``(company_id, state)`` is how an operator asks
"what is stuck for this company"; ``(state, updated_at)`` is how the sweep
finds resumable work oldest-first without scanning every tenant's rows.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID, UtcDateTime

revision: str = "c8a2f47b3d19"
down_revision: str | Sequence[str] | None = "b7e3d51a9c46"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_ingestion_jobs",
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
        sa.Column(
            "document_id",
            GUID(),
            sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("job_key", sa.String(length=120), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_reason", sa.String(length=40), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.Column("updated_at", UtcDateTime(), nullable=False),
        sa.UniqueConstraint("company_id", "job_key", name="uq_knowledge_ingestion_jobs_key"),
    )
    op.create_index(
        "ix_knowledge_ingestion_jobs_company_id", "knowledge_ingestion_jobs", ["company_id"]
    )
    op.create_index(
        "ix_knowledge_ingestion_jobs_source_message_id",
        "knowledge_ingestion_jobs",
        ["source_message_id"],
    )
    op.create_index(
        "ix_knowledge_ingestion_jobs_document_id", "knowledge_ingestion_jobs", ["document_id"]
    )
    op.create_index(
        "ix_knowledge_ingestion_jobs_company_state",
        "knowledge_ingestion_jobs",
        ["company_id", "state"],
    )
    op.create_index(
        "ix_knowledge_ingestion_jobs_state_updated",
        "knowledge_ingestion_jobs",
        ["state", "updated_at"],
    )


def downgrade() -> None:
    for index in (
        "ix_knowledge_ingestion_jobs_state_updated",
        "ix_knowledge_ingestion_jobs_company_state",
        "ix_knowledge_ingestion_jobs_document_id",
        "ix_knowledge_ingestion_jobs_source_message_id",
        "ix_knowledge_ingestion_jobs_company_id",
    ):
        op.drop_index(index, table_name="knowledge_ingestion_jobs")
    op.drop_table("knowledge_ingestion_jobs")
