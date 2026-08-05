"""A service's AI confidence threshold becomes genuinely optional.

The Services screen exposes a per-service confidence threshold, and the engine
was enforcing the company-wide one — the UI and the engine disagreeing about a
number that decides whether AI speaks to a customer.

Fixing that meant deciding what "the service does not define one" looks like,
and a NOT NULL column defaulting to 0.75 could not say it. With that default,
the one company on this installation that had deliberately set 0.7 company-wide
would have had it silently replaced the moment somebody created a service.
A default is indistinguishable from a choice; NULL is not.

Existing rows holding exactly the old column default are set to NULL, because
that value was written by the column and not by a person: the field was only
reachable through the API, never through a screen, until the same change that
made this migration necessary. A row holding any other value was set
deliberately and is left alone.

Verified against this installation before writing: ``service_versions`` holds
no rows at all, so the backfill below is a no-op here and exists for
environments that have some.

Revision ID: b8f04d6a2e17
Revises: a4e79b2c1f60
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b8f04d6a2e17"
down_revision: str | None = "a4e79b2c1f60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: What the column used to default to. Written out rather than imported so a
#: later change to the domain cannot silently re-target this migration.
_OLD_DEFAULT = "0.75"


def upgrade() -> None:
    op.alter_column(
        "service_versions",
        "ai_confidence_threshold",
        existing_type=sa.String(length=16),
        nullable=True,
    )
    op.execute(
        sa.text(
            "UPDATE service_versions SET ai_confidence_threshold = NULL "
            "WHERE ai_confidence_threshold = :old"
        ).bindparams(old=_OLD_DEFAULT)
    )


def downgrade() -> None:
    # Back to the old default, since the column cannot be NOT NULL with nulls
    # in it. This loses the distinction the upgrade introduced — a service
    # that deferred to the company becomes one that defines 0.75 — which is
    # exactly the ambiguity being removed, and is unavoidable going backwards.
    op.execute(
        sa.text(
            "UPDATE service_versions SET ai_confidence_threshold = :old "
            "WHERE ai_confidence_threshold IS NULL"
        ).bindparams(old=_OLD_DEFAULT)
    )
    op.alter_column(
        "service_versions",
        "ai_confidence_threshold",
        existing_type=sa.String(length=16),
        nullable=False,
    )
