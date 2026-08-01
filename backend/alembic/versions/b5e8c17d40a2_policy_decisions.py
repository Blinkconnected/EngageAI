"""routing decisions record policy evaluations

See ``docs/architecture/policy-engine.md``.

A policy must never silently allow or deny anything, so every evaluation that
gates behaviour is written here alongside the routing and service decisions —
one log, read in order, that explains a conversation end to end.

Four columns rather than JSON, unlike ``resolution_stages`` and
``rejected_candidates``. Those are read whole with their parent row; these are
what somebody *filters* by — "show me everything AI was refused for, and where
the refusal came from" — and a filter over a JSON key is a filter nobody
writes.

``policy_reason`` deliberately holds the policy module's own vocabulary rather
than a value from ``RoutingDecisionReason``. Copying a second closed set into
this table's enum would leave the two to drift, and the reason an
administrator filters on belongs to the rule, not to the log.

Adding columns to an append-only table is safe: the trigger refuses UPDATE and
DELETE of *rows*, and ALTER TABLE is neither. Existing rows get NULL, which is
honest — they were written before policies were recorded.

Revision ID: b5e8c17d40a2
Revises: a7f2b0c9e153
Create Date: 2026-08-01 13:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b5e8c17d40a2"
down_revision: str | None = "a7f2b0c9e153"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("routing_decisions", sa.Column("policy", sa.String(40), nullable=True))
    op.add_column("routing_decisions", sa.Column("policy_reason", sa.String(40), nullable=True))
    op.add_column("routing_decisions", sa.Column("policy_source", sa.String(30), nullable=True))
    op.add_column("routing_decisions", sa.Column("policy_text", sa.String(200), nullable=True))
    # "What did we refuse, and why" across a company — the query the Routing
    # Inspector's policy view runs. Partial on PostgreSQL so it costs nothing
    # for the routing and service decisions, which are most of the table.
    op.create_index(
        "ix_routing_decisions_policy",
        "routing_decisions",
        ["company_id", "policy", "decided_at"],
        postgresql_where=sa.text("policy IS NOT NULL"),
        sqlite_where=sa.text("policy IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_routing_decisions_policy", table_name="routing_decisions")
    op.drop_column("routing_decisions", "policy_text")
    op.drop_column("routing_decisions", "policy_source")
    op.drop_column("routing_decisions", "policy_reason")
    op.drop_column("routing_decisions", "policy")
