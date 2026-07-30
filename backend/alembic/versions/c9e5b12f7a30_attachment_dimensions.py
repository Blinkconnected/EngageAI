"""attachment pixel dimensions

See ``docs/architecture/conversations.md``.

Stored so the conversation can reserve the right amount of space *before*
an image loads. Without them a thread of photos reflows as each one
arrives, and on a long conversation that means an agent loses their place
mid-sentence — the single most noticeable performance defect in a chat UI,
and one that no amount of loading-spinner polish disguises.

NULL for everything not measurable. Existing attachments are left NULL
rather than backfilled: reading dimensions means fetching every historical
object out of storage, and the UI already has to handle NULL for video and
for files, so there is nothing to gain by guessing.

Revision ID: c9e5b12f7a30
Revises: e2d914a7b3c6
Create Date: 2026-07-30 06:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9e5b12f7a30"
down_revision: str | None = "e2d914a7b3c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("message_attachments", sa.Column("width", sa.Integer(), nullable=True))
    op.add_column("message_attachments", sa.Column("height", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("message_attachments", "height")
    op.drop_column("message_attachments", "width")
