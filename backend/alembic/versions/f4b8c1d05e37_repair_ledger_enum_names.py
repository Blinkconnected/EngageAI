"""repair ledger rows written with enum values instead of member names

``Enum(native_enum=False)`` stores the member **NAME**. The first version
of the ledger backfill wrote the enum *values* — ``'revenue_adjustments'``
rather than ``'REVENUE_ADJUSTMENTS'`` — which is valid SQL, passes every
constraint, and then raises ``LookupError`` the first time anything reads
the row. Every derived balance and every statement was affected.

It went unnoticed by the test suite because the suite runs on SQLite and
builds its schema from the ORM metadata: the backfill SQL only ever
executes against PostgreSQL, so no test exercised it. The corrected
backfill in ``d7f3a2e91c48`` now also asserts that no row holds a
non-name value, which fails loudly rather than at read time.

This migration repairs installations that already ran the broken version.
It is a no-op where the rows are already correct.

**It disables the append-only trigger to do so.** That is the whole point
of the trigger, and the exception is deliberate and narrow: these rows are
*reconstructed* entries whose stored text does not name a value the
application can read, so they are not evidence of anything — they are
corrupt. Rewriting the label is not an amendment of a financial fact; no
amount, account relationship, or ordering changes. A schema migration is
the one legitimate place to do it, and doing it in the open, once, is
safer than a trigger written to tolerate "some" updates.

Revision ID: f4b8c1d05e37
Revises: d7f3a2e91c48
Create Date: 2026-07-29 22:20:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f4b8c1d05e37"
down_revision: str | None = "d7f3a2e91c48"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: value -> member name, for the two enums the backfill wrote.
_ENTRY_TYPES = {
    "invoice.issued": "INVOICE_ISSUED",
    "credit_note.issued": "CREDIT_NOTE_ISSUED",
    "payment.received": "PAYMENT_RECEIVED",
    "payment.allocated": "PAYMENT_ALLOCATED",
    "payment.allocation_reversed": "ALLOCATION_REVERSED",
    "payment.refunded": "REFUND_ISSUED",
    "payment.chargeback": "CHARGEBACK",
    "receivable.written_off": "WRITE_OFF",
    "adjustment.manual": "MANUAL_ADJUSTMENT",
}

#: Account values happen to be the lowercase of their names, so a single
#: `upper()` is enough and cannot drift out of step with the enum.
_ACCOUNT_COLUMNS = ("debit_account", "credit_account")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        # The trigger and the backfill are both PostgreSQL-only; there is
        # nothing to repair on the SQLite test backend.
        return

    op.execute("ALTER TABLE ledger_entries DISABLE TRIGGER trg_ledger_entries_immutable")
    try:
        for value, name in _ENTRY_TYPES.items():
            op.execute(
                f"UPDATE ledger_entries SET entry_type = '{name}' "  # noqa: S608
                f"WHERE entry_type = '{value}'"
            )
        for column in _ACCOUNT_COLUMNS:
            op.execute(
                f"UPDATE ledger_entries SET {column} = upper({column}) "  # noqa: S608
                f"WHERE {column} <> upper({column})"
            )
    finally:
        # Restored even if a statement fails: leaving the ledger writable
        # would be a far worse outcome than a failed migration.
        op.execute("ALTER TABLE ledger_entries ENABLE TRIGGER trg_ledger_entries_immutable")

    op.execute(
        """
        DO $$
        DECLARE bad integer;
        BEGIN
          SELECT count(*) INTO bad FROM ledger_entries
          WHERE entry_type <> upper(entry_type)
             OR debit_account <> upper(debit_account)
             OR credit_account <> upper(credit_account);
          IF bad > 0 THEN
            RAISE EXCEPTION 'ledger repair left % unreadable row(s)', bad;
          END IF;
        END $$
        """
    )


def downgrade() -> None:
    # Deliberately empty. Putting unreadable labels back would restore a
    # defect, and a downgrade that reintroduces corruption is not a
    # downgrade anybody wants.
    pass
