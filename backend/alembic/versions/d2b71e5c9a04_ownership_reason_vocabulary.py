"""ownership reasons become the structured vocabulary

See ``docs/architecture/queue-lifecycle.md``.

Ownership is operational responsibility, and every change of it carries a
*structured* reason — never free text. This renames the stored codes onto the
vocabulary the model actually speaks, and adds the three it was missing:
``CUSTOMER_REPLIED``, ``ESCALATION`` and a first-placement reason distinct
from a later return to the queue.

The rename matters more than it looks. These strings are what a console
filters on and what every ownership metric groups by, so a code that means
two things — ``ENTERED_QUEUE`` covering both "the conversation arrived" and
"somebody handed it back" — makes "average time until pickup" unanswerable:
the query cannot tell the first row from the fourth.

``Enum(native_enum=False)`` stores the member NAME, so the stored values are
uppercase and the UPDATEs below match on that. Only backfilled rows exist so
far, all of them ``ENTERED_QUEUE``, and all of them genuinely first
placements — which is why they become ``NEW_CONVERSATION`` rather than being
left ambiguous.

Revision ID: d2b71e5c9a04
Revises: c1a4f6d82b39
Create Date: 2026-08-01 17:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d2b71e5c9a04"
down_revision: str | None = "c1a4f6d82b39"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: old → new. Kept as data so the downgrade is the same table reversed and
#: cannot drift from the upgrade.
_RENAMES: tuple[tuple[str, str], ...] = (
    ("ENTERED_QUEUE", "NEW_CONVERSATION"),
    ("PICKED_UP", "PICKED_BY_AGENT"),
    ("AI_ENGAGED", "AI_ENGAGEMENT"),
    ("AI_HANDED_OVER", "AI_RELEASED"),
    ("STICKY_WINDOW_EXPIRED", "OWNERSHIP_EXPIRED"),
    ("RELEASED_ON_RESOLVE", "CONVERSATION_RESOLVED"),
    ("RELEASED_ON_CLOSE", "CONVERSATION_CLOSED"),
    ("TRANSFERRED", "MANUAL_TRANSFER"),
    ("SUPERVISOR_TOOK_OVER", "SUPERVISOR_OVERRIDE"),
    ("RELEASED", "RELEASED_BY_OWNER"),
)


def upgrade() -> None:
    for old, new in _RENAMES:
        op.execute(
            f"UPDATE conversation_ownership SET reason = '{new}' WHERE reason = '{old}'"  # noqa: S608
        )


def downgrade() -> None:
    for old, new in _RENAMES:
        op.execute(
            f"UPDATE conversation_ownership SET reason = '{old}' WHERE reason = '{new}'"  # noqa: S608
        )
