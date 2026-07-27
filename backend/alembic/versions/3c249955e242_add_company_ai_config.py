"""add company ai_config (per-company AI provider override)

Revision ID: 3c249955e242
Revises: 1f2a3b4c5d6e
Create Date: 2026-07-27 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "3c249955e242"
down_revision: str | None = "1f2a3b4c5d6e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # LargeBinary, not JSON — this column holds an AES-256-GCM-encrypted
    # blob (infrastructure.database.encrypted_json.EncryptedJSON), the
    # same "dedicated encrypted column" pattern channel_configs.credentials
    # already established, since this dict carries a real secret (the
    # provider API key) unlike Company.settings' plain-JSON blob.
    op.add_column("companies", sa.Column("ai_config", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    op.drop_column("companies", "ai_config")
