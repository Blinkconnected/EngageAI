"""usage_records is append-only, enforced by the database

See ``docs/architecture/billing.md``.

Metering records must be immutable forever. That was true in the code — the
repository exposes ``add`` and reads, nothing else — but the database did not
say so, while its sibling ``billable_events`` did. A rule enforced in one
layer is a rule somebody eventually goes around, and the way around this one
is a single UPDATE in a psql session.

So ``usage_records`` gets the trigger its sibling has. A measurement is a
fact: it happened, at a time, in a quantity. Correcting one is a *new*
record — the usage engine already has ``UsageRecordSource.MANUAL`` for
exactly that, so nothing legitimate needs an edit.

The dev-reset script (``scripts/reset_company_billing.sql``) disables the
other append-only triggers explicitly and now disables this one too; that is a
named, deliberate development tool, not a production path.

Revision ID: b7d4e21a9c56
Revises: a2f61d9c4e83
Create Date: 2026-07-30 20:15:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b7d4e21a9c56"
down_revision: str | Sequence[str] | None = "a2f61d9c4e83"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(
        """
        CREATE OR REPLACE FUNCTION usage_records_immutable()
        RETURNS TRIGGER AS $$
        BEGIN
          RAISE EXCEPTION
            'usage_records is append-only: a measurement is a fact, and a '
            'correction is a new record (see UsageRecordSource.MANUAL) rather '
            'than an edit';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_usage_records_immutable
        BEFORE UPDATE OR DELETE ON usage_records
        FOR EACH ROW EXECUTE FUNCTION usage_records_immutable()
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP TRIGGER IF EXISTS trg_usage_records_immutable ON usage_records")
    op.execute("DROP FUNCTION IF EXISTS usage_records_immutable()")
