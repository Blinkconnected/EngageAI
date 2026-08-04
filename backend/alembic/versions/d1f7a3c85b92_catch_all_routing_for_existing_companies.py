"""Every existing company gets somewhere for a message to land.

Registration now seeds a ``General`` queue and a catch-all routing rule, so a
company created from here on is operable the moment it exists. Companies that
already existed got nothing: the seed runs at registration, and registration
already happened for them.

This is what that left behind on this installation, measured before writing:

============================================  ====
Companies                                       35
...with an active catch-all rule                 0
...with no live queue at all                    34
============================================  ====

Every one of them silently dropped any conversation that did not match a
specific rule. Routing recorded it accurately — ``LEFT_UNROUTED`` /
``NO_RULE_MATCHED`` — and then the conversation sat with ``queue_id IS NULL``,
which the Inbox classifies *critical* and which no agent has any reason to be
looking at. AI never saw it either: Autopilot is a queue worker, so a
conversation that reaches no queue is a conversation AI is never offered.

The failure this was found through is worth recording, because it is the one a
customer would hit. An administrator configured AI, configured an SLA policy,
sent a test message and waited five minutes for a reply that was never coming
— the company's only routing rule required the message body to contain a
particular string, so nothing else reached a queue at all. Nothing in the
product said so anywhere they were looking.

**What this writes, per company that lacks one:**

- A catch-all rule at priority 1000 — the lowest precedence there is, so every
  rule an administrator has already written outranks it. It claims only what
  nothing else claimed, which is why this is additive: a conversation that
  routes correctly today routes identically afterwards, and a conversation
  that reaches nothing today reaches a queue instead.
- Pointing at the company's **oldest live queue** where there is one — the
  queue they set up first, rather than a new one they would have to notice —
  and at a newly created ``General`` otherwise.

**Idempotent.** A company that already has an active catch-all reaching a live
queue is skipped, so re-running finds nothing to do.

**The downgrade deliberately does nothing.** Once written, these rows are
ordinary configuration the administrator owns: renameable, editable,
deletable, and indistinguishable from a queue and a rule they made themselves.
Deleting routing configuration on a downgrade would be destroying a tenant's
own work to undo a schema step that changed no schema.

Revision ID: d1f7a3c85b92
Revises: b8f04d6a2e17
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d1f7a3c85b92"
down_revision: str | None = "b8f04d6a2e17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Written out rather than imported from ``auth_service``. A migration
#: describes what it did to a database on the day it ran; if the application's
#: idea of a default queue changes later, this must not change with it.
_QUEUE_NAME = "General"
_QUEUE_DESCRIPTION = "Every conversation arrives here until you add queues of your own."
_RULE_PRIORITY = 1000
#: ``Enum(..., native_enum=False)`` stores the member *name*.
_STRATEGY = "MANUAL"


def _free_queue_name(connection: sa.Connection, company_id: uuid.UUID) -> str:
    """``General``, or the first suffixed variant nobody is using.

    ``uq_queues_company_name`` is unique per company over rows that are not
    soft-deleted. A company holding an inactive queue already called
    ``General`` is unlikely, but an INSERT that raises on it would abort the
    whole migration for every other tenant — and reactivating or renaming
    somebody's existing queue to make room is a worse answer than picking a
    different name.
    """
    taken = {
        row[0]
        for row in connection.execute(
            sa.text(
                "SELECT name FROM queues " "WHERE company_id = :company AND deleted_at IS NULL"
            ),
            {"company": company_id},
        )
    }
    if _QUEUE_NAME not in taken:
        return _QUEUE_NAME
    suffix = 2
    while f"{_QUEUE_NAME} {suffix}" in taken:
        suffix += 1
    return f"{_QUEUE_NAME} {suffix}"


def upgrade() -> None:
    connection = op.get_bind()

    # Companies whose conversations already have somewhere to fall through to.
    # The join matters: a catch-all pointing at a deleted or deactivated queue
    # routes nothing, so it does not count as having one.
    covered = {
        row[0]
        for row in connection.execute(
            sa.text(
                "SELECT DISTINCT r.company_id "
                "FROM routing_rules r "
                "JOIN queues q ON q.id = r.target_queue_id "
                "WHERE r.is_active "
                "  AND q.deleted_at IS NULL "
                "  AND q.is_active "
                "  AND r.conditions::text IN ('{}', '{ }')"
            )
        )
    }

    companies = [
        row[0]
        for row in connection.execute(
            sa.text("SELECT id FROM companies WHERE deleted_at IS NULL ORDER BY created_at")
        )
    ]

    for company_id in companies:
        if company_id in covered:
            continue

        # The oldest live queue: the one this company set up first, and so
        # the one an administrator is most likely to already be watching.
        # Creating a new queue beside a working one would put their fallback
        # somewhere they have never opened.
        target = connection.execute(
            sa.text(
                "SELECT id FROM queues "
                "WHERE company_id = :company AND deleted_at IS NULL AND is_active "
                "ORDER BY created_at LIMIT 1"
            ),
            {"company": company_id},
        ).scalar()

        if target is None:
            target = uuid.uuid4()
            connection.execute(
                sa.text(
                    "INSERT INTO queues "
                    "(id, company_id, name, description, assignment_strategy, "
                    " is_active, autopilot_enabled) "
                    "VALUES (:id, :company, :name, :description, :strategy, true, false)"
                ),
                {
                    "id": target,
                    "company": company_id,
                    "name": _free_queue_name(connection, company_id),
                    "description": _QUEUE_DESCRIPTION,
                    "strategy": _STRATEGY,
                },
            )

        connection.execute(
            sa.text(
                "INSERT INTO routing_rules "
                "(id, company_id, priority, conditions, target_queue_id, is_active) "
                "VALUES (:id, :company, :priority, '{}', :target, true)"
            ),
            {
                "id": uuid.uuid4(),
                "company": company_id,
                "priority": _RULE_PRIORITY,
                "target": target,
            },
        )


def downgrade() -> None:
    """Intentionally empty — see the module docstring."""
