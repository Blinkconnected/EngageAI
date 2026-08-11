"""Structured knowledge records

Revision ID: e2b9d47f1a83
Revises: d3f8a1c62e94
Create Date: 2026-08-11 00:40:00.000000

See ``docs/architecture/company-knowledge-and-voice.md``.

The table a price lives in. Deliberately not a row in ``knowledge_articles``
(prose, found by resemblance) and not one in ``memory_facts`` (evidential,
decays without re-observation): an approved price is a value found by
identity, true over a period, authoritative because a human approved the
document it came from.

**No ``deleted_at``.** Withdrawal is ``ARCHIVED`` and replacement is
``SUPERSEDED``; both stay readable forever. A price that was quoted must be
reproducible in an audit two years later, and a soft-delete filter is
exactly how it would stop being.

The overlap rule — no two ``ACTIVE`` records sharing an instant for one
subject — is **not** a constraint here. PostgreSQL could express it as an
exclusion constraint over a ``tstzrange``; SQLite cannot, and this codebase
runs its test suite on SQLite. Enforcing it in one dialect only would mean
the rule holds in production and not in the tests that claim to check it,
which is worse than enforcing it in the service where both see the same
code. It is enforced in ``KnowledgeRecordService`` inside the write
transaction and asserted by integration tests on both dialects.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID, UtcDateTime

revision: str = "e2b9d47f1a83"
down_revision: str | Sequence[str] | None = "d3f8a1c62e94"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_records",
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column("created_at", UtcDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", UtcDateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("company_id", GUID(), nullable=False),
        sa.Column("record_type", sa.String(length=32), nullable=False),
        sa.Column("subject_key", sa.String(length=200), nullable=False),
        sa.Column("subject_label", sa.String(length=300), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column(
            "attributes_schema_version", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column("effective_from", UtcDateTime(), nullable=False),
        sa.Column("effective_until", UtcDateTime(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("supersedes_id", GUID(), nullable=True),
        sa.Column("superseded_by_id", GUID(), nullable=True),
        sa.Column(
            "lifecycle_state",
            sa.String(length=16),
            server_default=sa.text("'DRAFT'"),
            nullable=False,
        ),
        sa.Column(
            "access_level",
            sa.String(length=16),
            server_default=sa.text("'PUBLIC_TO_AI'"),
            nullable=False,
        ),
        sa.Column("created_from", sa.String(length=24), nullable=False),
        # Stays FK-less until M2D introduces the documents table it points
        # at. Adding the constraint then is a migration; inventing a table
        # now to satisfy a column would be building M2D early.
        sa.Column("source_document_version_id", GUID(), nullable=True),
        sa.Column("source_reference", sa.Text(), nullable=True),
        sa.Column("approved_by_user_id", GUID(), nullable=True),
        sa.Column("approved_at", UtcDateTime(), nullable=True),
        sa.Column("archived_at", UtcDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        # RESTRICT on the chain links: the version chain *is* the audit
        # trail, and deleting a link would silently orphan every version
        # after it.
        sa.ForeignKeyConstraint(["supersedes_id"], ["knowledge_records.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["superseded_by_id"], ["knowledge_records.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "company_id",
            "record_type",
            "subject_key",
            "version",
            name="uq_knowledge_records_subject_version",
        ),
    )
    op.create_index(
        "ix_knowledge_records_company_id", "knowledge_records", ["company_id"], unique=False
    )
    # The resolution query: one company's records for a subject of a type,
    # narrowed by period. The range column goes last.
    op.create_index(
        "ix_knowledge_records_resolution",
        "knowledge_records",
        ["company_id", "record_type", "subject_key", "effective_from"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_records_chain",
        "knowledge_records",
        ["company_id", "subject_key", "version"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_records_company_state",
        "knowledge_records",
        ["company_id", "lifecycle_state"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_records_company_state", table_name="knowledge_records")
    op.drop_index("ix_knowledge_records_chain", table_name="knowledge_records")
    op.drop_index("ix_knowledge_records_resolution", table_name="knowledge_records")
    op.drop_index("ix_knowledge_records_company_id", table_name="knowledge_records")
    op.drop_table("knowledge_records")
