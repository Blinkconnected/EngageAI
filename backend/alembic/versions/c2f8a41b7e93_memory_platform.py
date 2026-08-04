"""The Memory Platform: facts, their evidence, and their confidence history.

Stage 2 of the Company Intelligence Engine, and a **platform bounded
context** rather than a feature of the AI Engine. Knowledge answers "what
is true?"; Memory answers "what happened?". The AI Engine will be one
consumer among several — the Workflow Engine, CRM, Reporting, the Customer
Timeline and Analytics are the others — and none of them writes here
except through the Memory Manager.

Three tables, and the shape of them is the design:

``memory_facts`` holds all three durable tiers (organizational, customer,
experience) rather than one table each. They share the entire contract and
differ only in vocabulary and subject, so three tables would mean three
copies of the decay, lifecycle and erasure code. The decisive argument is
erasure: a customer request must delete that customer's facts *and* weaken
the aggregate facts their conversations supported, in one transaction —
against one table that is one delete and one recompute, and across three
it is a dance where a missed table is a compliance failure that looks like
nothing.

``memory_evidence`` is why a fact is believed, as **pointers, never
copies**. Storing an excerpt here would put customer content into a second
store with different retention and a different permission, and would turn
erasure from a row deletion into a text-editing problem. ``customer_id``
is denormalised onto it because that is what an erasure request joins on,
and resolving it through the conversation later would make erasure depend
on a row a conversation purge may already have removed.

``memory_confidence_samples`` is what makes ``confidence_direction``
meaningful. Direction is computed from evidence deltas here rather than by
differencing the confidence column, because confidence already includes
recency decay — differencing it would report FALLING for every fact that
is merely quiet, which is most facts, and the column would become a
noisier restatement of DORMANT.

**No soft delete on any of them**, which is deliberate and unlike every
other entity in this schema. These tables are subject to erasure requests,
and a store promising both immutability and deletion is promising one of
them falsely. Decay archives; erasure deletes.

Revision ID: c2f8a41b7e93
Revises: b1c7e94d3a52
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision: str = "c2f8a41b7e93"
down_revision: str | Sequence[str] | None = "b1c7e94d3a52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_facts",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "company_id",
            GUID(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tier", sa.String(length=20), nullable=False),
        sa.Column("fact_type", sa.String(length=48), nullable=False),
        sa.Column("fact_key", sa.String(length=200), nullable=False),
        # Polymorphic subject, so no foreign key: a fact may be about a
        # company, a customer or an agent. Integrity is the erasure
        # service's job, asserted by a test — the same trade already made
        # for `embeddings.owner_id`.
        sa.Column("subject_type", sa.String(length=16), nullable=False),
        sa.Column("subject_id", GUID(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column(
            "attributes_schema_version", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False, server_default="0"),
        sa.Column("confidence_computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "confidence_state", sa.String(length=16), nullable=False, server_default="observed"
        ),
        sa.Column(
            "confidence_direction",
            sa.String(length=16),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column(
            "lifecycle_state", sa.String(length=16), nullable=False, server_default="active"
        ),
        sa.Column("support_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("distinct_customer_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("distinct_agent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("contradiction_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("outcome_quality", sa.Numeric(5, 4), nullable=True),
        sa.Column(
            "has_corroboration", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_from", sa.String(length=24), nullable=False),
        sa.Column(
            "created_by_user_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "steward_user_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("steward_role", sa.String(length=64), nullable=True),
        sa.Column(
            "human_state", sa.String(length=16), nullable=False, server_default="unreviewed"
        ),
        sa.Column(
            "human_state_by_user_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("human_state_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pipeline_version", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        # The dedupe identity. Without it a second observation creates a
        # sibling row, the support splits between them, and a fact seen a
        # hundred times crosses no threshold.
        sa.UniqueConstraint(
            "company_id",
            "tier",
            "subject_type",
            "subject_id",
            "fact_type",
            "fact_key",
            name="uq_memory_facts_identity",
        ),
    )
    op.create_index("ix_memory_facts_company_id", "memory_facts", ["company_id"])
    op.create_index(
        "ix_memory_facts_subject", "memory_facts", ["company_id", "subject_type", "subject_id"]
    )
    op.create_index(
        "ix_memory_facts_company_tier_state",
        "memory_facts",
        ["company_id", "tier", "lifecycle_state"],
    )
    op.create_index(
        "ix_memory_facts_decay_due",
        "memory_facts",
        ["confidence_computed_at"],
        postgresql_where=sa.text("lifecycle_state <> 'purged'"),
        sqlite_where=sa.text("lifecycle_state <> 'purged'"),
    )
    op.create_index(
        "ix_memory_facts_due",
        "memory_facts",
        ["company_id", "due_at"],
        postgresql_where=sa.text("due_at IS NOT NULL"),
        sqlite_where=sa.text("due_at IS NOT NULL"),
    )

    op.create_table(
        "memory_evidence",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "company_id",
            GUID(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "fact_id",
            GUID(),
            sa.ForeignKey("memory_facts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(length=24), nullable=False),
        sa.Column("source_id", GUID(), nullable=True),
        sa.Column(
            "conversation_id",
            GUID(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "customer_id",
            GUID(),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=True,
        ),
        # SET NULL, unlike the two above: an agent leaving must not delete
        # the evidence that a practice worked. The person is detached; the
        # observation stands.
        sa.Column(
            "agent_id", GUID(), sa.ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("weight", sa.Numeric(5, 4), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        # Re-observing the same source is idempotent. At-least-once
        # delivery makes replay the normal case, and without this a replay
        # inflates exactly the counters confidence is computed from.
        sa.UniqueConstraint(
            "fact_id", "source_type", "source_id", name="uq_memory_evidence_source"
        ),
    )
    op.create_index("ix_memory_evidence_company_id", "memory_evidence", ["company_id"])
    op.create_index("ix_memory_evidence_fact", "memory_evidence", ["fact_id"])
    op.create_index(
        "ix_memory_evidence_customer", "memory_evidence", ["company_id", "customer_id"]
    )
    op.create_index(
        "ix_memory_evidence_conversation", "memory_evidence", ["company_id", "conversation_id"]
    )

    op.create_table(
        "memory_confidence_samples",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "company_id",
            GUID(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "fact_id",
            GUID(),
            sa.ForeignKey("memory_facts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("supporting_delta", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("contradicting_delta", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_memory_confidence_samples_company_id", "memory_confidence_samples", ["company_id"]
    )
    op.create_index(
        "ix_memory_confidence_samples_fact",
        "memory_confidence_samples",
        ["fact_id", "computed_at"],
    )
    op.create_index(
        "ix_memory_confidence_samples_pruning", "memory_confidence_samples", ["computed_at"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_memory_confidence_samples_pruning", table_name="memory_confidence_samples"
    )
    op.drop_index("ix_memory_confidence_samples_fact", table_name="memory_confidence_samples")
    op.drop_index(
        "ix_memory_confidence_samples_company_id", table_name="memory_confidence_samples"
    )
    op.drop_table("memory_confidence_samples")

    op.drop_index("ix_memory_evidence_conversation", table_name="memory_evidence")
    op.drop_index("ix_memory_evidence_customer", table_name="memory_evidence")
    op.drop_index("ix_memory_evidence_fact", table_name="memory_evidence")
    op.drop_index("ix_memory_evidence_company_id", table_name="memory_evidence")
    op.drop_table("memory_evidence")

    op.drop_index("ix_memory_facts_due", table_name="memory_facts")
    op.drop_index("ix_memory_facts_decay_due", table_name="memory_facts")
    op.drop_index("ix_memory_facts_company_tier_state", table_name="memory_facts")
    op.drop_index("ix_memory_facts_subject", table_name="memory_facts")
    op.drop_index("ix_memory_facts_company_id", table_name="memory_facts")
    op.drop_table("memory_facts")
