"""Soft-delete User rows orphaned by agents deleted before the cascade fix

Revision ID: 6b6f167ff303
Revises: 040a7da326b5
Create Date: 2026-07-28

``AgentService.delete()`` only soft-deleted the ``Agent`` profile until
this release, leaving its backing ``User`` row live forever. Because
``users.email`` uniqueness now excludes soft-deleted rows (migration
``040a7da326b5``), those already-orphaned rows are the one remaining
thing still blocking their email addresses from being reused — the
service-layer fix only applies to *future* deletions, so without this
backfill an agent deleted before upgrading could still never be re-added.

Scope is deliberately narrow. A user is only soft-deleted when **all**
of these hold:

- they have at least one soft-deleted ``Agent`` profile,
- they have **no** active (non-deleted) ``Agent`` profile — a user whose
  agent row was re-created still needs their login,
- they are not a company owner (``is_company_owner``) — an owner is a
  login identity in their own right, not an agent profile, and may well
  have had an agent profile deleted while still owning the company.

``deleted_at`` is backdated to the agent's own ``deleted_at`` rather than
"now", so the audit trail reflects when the account actually stopped
being usable, not when this migration happened to run.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6b6f167ff303"
down_revision: str | None = "040a7da326b5"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE users AS u
            SET deleted_at = latest_deleted.deleted_at
            FROM (
                SELECT a.user_id, MAX(a.deleted_at) AS deleted_at
                FROM agents AS a
                WHERE a.deleted_at IS NOT NULL
                GROUP BY a.user_id
            ) AS latest_deleted
            WHERE u.id = latest_deleted.user_id
              AND u.deleted_at IS NULL
              AND u.is_company_owner = false
              AND NOT EXISTS (
                  SELECT 1 FROM agents AS active
                  WHERE active.user_id = u.id AND active.deleted_at IS NULL
              )
            """
        )
    )


def downgrade() -> None:
    # Intentionally irreversible: the pre-migration state ("this user is
    # live even though their only agent profile is deleted") is precisely
    # the bug, and nothing records which rows this backfill touched, so
    # restoring them would mean guessing — and would re-block the very
    # email addresses the upgrade freed. Rolling back the schema change in
    # 040a7da326b5 does not require these rows to be resurrected.
    pass
