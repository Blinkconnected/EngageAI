"""device tokens, and a push dispatch watermark on notifications

See ``docs/architecture/notifications.md``.

Push notifications need two things the schema did not have: somewhere to
record which devices a user has, and a way to tell which notifications
have already been pushed.

``device_tokens.token`` is **globally unique**, not unique per user. A
push token identifies an app install on a device, and the operating system
hands it to whoever is signed in — so a second person signing into a
shared phone must *take over* that row rather than add a second one, or
the provider keeps delivering the first person's alerts to a device they
no longer hold. Registration upserts on the token for that reason; the
unique constraint is what makes the rule enforceable rather than merely
intended.

``notifications.push_dispatched_at`` is a second watermark alongside
``email_dispatched_at`` rather than a shared one. The two transports
succeed and fail independently: an email that went out while a push is
still being retried is an ordinary state, and one column could not
represent it. Each gets its own partial index because each sweep claims
its own pending set, and both sets are a tiny fraction of the table.

Backfilled as NULL — meaning "not yet pushed" — with the sweep bounded to
recently-created notifications, so switching push on does not fire a
backlog of stale alerts at everybody. See the dispatch task for that
window.

Revision ID: c4b81e6f209d
Revises: f9a3c27d60b8
Create Date: 2026-07-30 10:42:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4b81e6f209d"
down_revision: str | None = "f9a3c27d60b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "device_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token", sa.String(length=255), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("device_name", sa.String(length=120), nullable=True),
        sa.Column("last_registered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token", name="uq_device_tokens_token"),
    )
    op.create_index("ix_device_tokens_company_id", "device_tokens", ["company_id"])
    op.create_index("ix_device_tokens_user", "device_tokens", ["user_id"])
    op.create_index("ix_device_tokens_token", "device_tokens", ["token"])

    op.add_column(
        "notifications",
        sa.Column("push_dispatched_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_notifications_unpushed",
        "notifications",
        ["push_dispatched_at"],
        postgresql_where=sa.text("push_dispatched_at IS NULL"),
        sqlite_where=sa.text("push_dispatched_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_unpushed", table_name="notifications")
    op.drop_column("notifications", "push_dispatched_at")
    op.drop_index("ix_device_tokens_token", table_name="device_tokens")
    op.drop_index("ix_device_tokens_user", table_name="device_tokens")
    op.drop_index("ix_device_tokens_company_id", table_name="device_tokens")
    op.drop_table("device_tokens")
