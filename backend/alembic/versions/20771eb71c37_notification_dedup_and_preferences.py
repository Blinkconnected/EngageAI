"""notification dedup and preferences

Revision ID: 20771eb71c37
Revises: 3000cabd1c86
Create Date: 2026-07-25 16:00:00.000000

Two independent additions for Sprint 2 Item 5 (Inbox Notifications,
reframed as a generic platform notification framework):

1. ``notifications.source_event_id`` (+ a unique constraint with
   ``user_id`` and ``notification_type``) — the idempotency key that
   prevents a duplicate notification row when RabbitMQ redelivers the
   same event under its at-least-once delivery guarantee. See
   ``NotificationService.create()``'s docstring. Includes
   ``notification_type`` (not just ``source_event_id``+``user_id``) so a
   built-in rule and a company's own ``create_notification`` workflow
   action never collide just because they happen to target the same
   user for the same triggering event — see
   ``docs/architecture/notifications.md`` for the one narrower case this
   still doesn't cover (two ``create_notification`` steps, same
   hardcoded type, same user, same event) and why that's an accepted,
   documented limit rather than something this migration tries to solve.
2. ``notification_preferences`` — per-user (notification_type, channel)
   delivery overrides. See ``domain/notification_types.py``.

``notifications`` already exists and is actively written to (unlike
``notification_preferences``, created fresh below) — a plain
``ALTER TABLE ... ADD CONSTRAINT ... UNIQUE`` takes an ACCESS EXCLUSIVE
lock for the full underlying index build, blocking every read/write
against it for that duration. Built ``CREATE UNIQUE INDEX CONCURRENTLY``
+ ``ADD CONSTRAINT ... UNIQUE USING INDEX`` instead on Postgres — the
standard two-step that avoids that lock — since this codebase's own
deployment docs describe a zero-downtime rolling-deploy goal this would
otherwise directly undermine. ``CREATE INDEX CONCURRENTLY`` cannot run
inside a transaction, hence ``autocommit_block()`` around just that one
statement; everything else in this migration still runs in the normal
migration transaction. SQLite (this repo's tests never run Alembic
migrations at all — they build schema via ``Base.metadata.create_all()``
— but keeping this correct for the CLI/a hypothetical SQLite deployment
matches this codebase's existing dialect-branching convention, e.g.
``GUID``) has no ``CONCURRENTLY``/table population size to protect
against, so it takes the plain, single-step path.

``autocommit_block()`` ends the migration's normal transaction to run the
``CONCURRENTLY`` statement, then opens a new one for whatever follows —
so, unlike every other migration in this codebase (one atomic
transaction, all-or-nothing), a process kill between the index build and
the version-stamp update at the very end of ``upgrade()`` can leave this
one committed partway: the column and/or index already present, but the
constraint/``notification_preferences`` table not yet, and
``alembic_version`` still one revision behind. Confirmed live — a
container killed mid-migration during a multi-container startup left
exactly that state. ``IF NOT EXISTS``/existence checks below make
re-running ``upgrade()`` from any of those partial states converge
correctly instead of failing on "already exists", the same property a
single-transaction migration gets for free.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision: str = "20771eb71c37"
down_revision: str | None = "3000cabd1c86"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOTIFICATIONS_UNIQUE_CONSTRAINT = "uq_notifications_source_event_user"
_NOTIFICATIONS_UNIQUE_COLUMNS = ["source_event_id", "user_id", "notification_type"]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_columns = {col["name"] for col in inspector.get_columns("notifications")}
    if "source_event_id" not in existing_columns:
        op.add_column("notifications", sa.Column("source_event_id", GUID(), nullable=True))

    if bind.dialect.name == "postgresql":
        columns_sql = ", ".join(_NOTIFICATIONS_UNIQUE_COLUMNS)
        with op.get_context().autocommit_block():
            op.execute(
                f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "
                f"{_NOTIFICATIONS_UNIQUE_CONSTRAINT} ON notifications ({columns_sql})"
            )
        existing_constraints = {
            c["name"] for c in inspect(op.get_bind()).get_unique_constraints("notifications")
        }
        if _NOTIFICATIONS_UNIQUE_CONSTRAINT not in existing_constraints:
            op.execute(
                f"ALTER TABLE notifications ADD CONSTRAINT {_NOTIFICATIONS_UNIQUE_CONSTRAINT} "
                f"UNIQUE USING INDEX {_NOTIFICATIONS_UNIQUE_CONSTRAINT}"
            )
    elif _NOTIFICATIONS_UNIQUE_CONSTRAINT not in {
        c["name"] for c in inspector.get_unique_constraints("notifications")
    }:
        op.create_unique_constraint(
            _NOTIFICATIONS_UNIQUE_CONSTRAINT, "notifications", _NOTIFICATIONS_UNIQUE_COLUMNS
        )

    if inspect(op.get_bind()).has_table("notification_preferences"):
        return

    op.create_table(
        "notification_preferences",
        sa.Column("id", GUID(), nullable=False),
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
        sa.Column("user_id", GUID(), nullable=False),
        sa.Column("notification_type", sa.String(length=100), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "notification_type",
            "channel",
            name="uq_notification_preferences_user_type_channel",
        ),
    )
    op.create_index("ix_notification_preferences_user_id", "notification_preferences", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_notification_preferences_user_id", table_name="notification_preferences")
    op.drop_table("notification_preferences")
    op.drop_constraint(_NOTIFICATIONS_UNIQUE_CONSTRAINT, "notifications", type_="unique")
    op.drop_column("notifications", "source_event_id")
