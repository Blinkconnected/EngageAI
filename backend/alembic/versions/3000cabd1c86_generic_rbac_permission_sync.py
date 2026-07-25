"""generic RBAC permission sync

Revision ID: 3000cabd1c86
Revises: 8a08ed1c4d83
Create Date: 2026-07-25 14:30:00.000000

No schema changes. Runs the new generic, reusable permission-sync
mechanism (``infrastructure.database.permission_sync.sync_permissions``)
once, reconciling *every* existing company's system-role permission
grants against ``domain.rbac.py``'s current definitions.

This is the last "backfill" migration this codebase should ever need:
every prior "seed a new permission" migration (``5463a5076e76``,
``7c6ca45d6fac``, ``c3d4e5f6a7b8``, ``e5f6a7b8c9d0``, ``a7b8c9d0e1f2``,
``d0e1f2a3b4c5``) only ever inserted into the ``permissions`` catalog and
never backfilled ``role_permissions`` for companies that already existed
at the time (``8a08ed1c4d83`` was the first to backfill anything, and
only for the one permission it introduced). Because ``sync_permissions``
diffs each company's *current* grants against the *current*
``DEFAULT_ROLE_PERMISSIONS`` rather than a fixed point-in-time list, this
one migration closes every one of those historical gaps in a single
pass, not just the one Item 4 fixed — see
``docs/architecture/auth-rbac.md`` for the full mechanism and
``docs/ROADMAP.md`` for the verification performed.

Going forward, adding a new permission (or extending an existing role's
default set) needs no migration like this at all: just update
``domain/rbac.py`` — ``core/migrate.py`` runs this same sync on every
container startup, automatically.
"""

from collections.abc import Sequence

from sqlalchemy.orm import Session

from alembic import op
from blinkengage.infrastructure.database.permission_sync import sync_permissions

revision: str = "3000cabd1c86"
down_revision: str | None = "8a08ed1c4d83"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    session = Session(bind=op.get_bind())
    sync_permissions(session)  # flushes internally; Alembic owns the commit


def downgrade() -> None:
    """Not reversible, deliberately: this migration reconciles every
    company's granted permissions against domain.rbac.py's definitions
    *at the time it runs*, additively. There is no recorded "before"
    state to restore — undoing it would mean guessing which of the
    now-granted rows already existed versus were newly backfilled, which
    isn't tracked anywhere. A no-op, same as the effect of this migration
    itself would be if run again (idempotent)."""
