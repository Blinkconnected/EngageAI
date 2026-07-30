"""billable events, volume pricing tiers, and the message-based billing model

See ``docs/architecture/billing.md``.

Three changes, one release, because they are one product decision:

**``billable_events``** — one immutable row per customer-facing message. The
evidence layer under the bill: a usage record says "a billable message
happened", this says which message, on which channel, in which conversation,
from whom. ``message_id`` is unique, so a redelivered event or two racing
workers converge on one row instead of charging twice — the guarantee belongs
to the database, not to a consumer.

**``pricing_rate_tiers``** — volume tiers under an existing rate. A rate with
no tier rows keeps behaving exactly as it does today; one with tiers charges
every chargeable unit at the rate its *total* volume selects. Child rows
rather than JSON so the shape is constrained by the database (ascending
bounds, non-negative rates) and readable by the audit trail.

**``usage_period_lines.tier_up_to``** — which tier produced the rate on a
frozen line. Added so an invoice can state *why* that rate applied years
later, without re-deriving it from a table that has since changed. Nullable:
every line written before this release was priced flat, and a backfilled
"tier" would be a fact nobody measured.

The seeded rates are the tier table the product ships with: the first 100
messages free (``domain/allowances.py``), then 0.002 up to 200 messages,
0.0015 up to 500, and 0.001 above that — in USD, with the JOD table at the
same ratio the existing conversation rates use.

**``CONVERSATION``, ``AI_AUTOPILOT`` and ``AI_ASSISTED_REPLY`` are retired,
not deleted.** Their rates, usage records, snapshot lines and invoices stay
exactly as they are: a closed month must keep pricing the way it was billed.
They simply stop being metered — see ``domain/billable_metrics.py``.

Revision ID: e8c3f47a1b60
Revises: c4b81e6f209d
Create Date: 2026-07-30 10:50:00.000000
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID, UtcDateTime

revision: str = "e8c3f47a1b60"
down_revision: str | Sequence[str] | None = "c4b81e6f209d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AMOUNT = sa.Numeric(18, 6)

#: The lower bound of a seeded global rate — the Unix epoch, matching
#: ``PRICING_EPOCH``. Deliberately not the migration's own timestamp: usage
#: predating this release must still resolve to *something*.
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

#: The shipped table, as (up_to, USD rate, JOD rate).
#:
#: The JOD column is the USD one at 0.7 — the same ratio as the existing
#: conversation pair (0.050 / 0.035), so the two currencies stay in the
#: relationship an operator already agreed to rather than one invented here.
_TIERS: tuple[tuple[int | None, str, str], ...] = (
    (200, "0.002000", "0.001400"),
    (500, "0.001500", "0.001050"),
    (None, "0.001000", "0.000700"),
)


def upgrade() -> None:
    op.create_table(
        "billable_events",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "company_id",
            GUID(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # RESTRICT, like invoices and the daily summary: this is the evidence
        # behind a charge, and deleting a period must not destroy it.
        sa.Column(
            "billing_period_id",
            GUID(),
            sa.ForeignKey("billing_periods.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # No foreign key to messages or conversations, deliberately: a
        # retention policy may delete a conversation, and the billing evidence
        # for an invoiced month has to survive that.
        sa.Column("message_id", GUID(), nullable=False),
        sa.Column("conversation_id", GUID(), nullable=False),
        sa.Column("customer_id", GUID(), nullable=True),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("origin", sa.String(20), nullable=False),
        sa.Column("channel_type", sa.String(40), nullable=False),
        sa.Column("message_type", sa.String(20), nullable=False),
        sa.Column("occurred_at", UtcDateTime(), nullable=False),
        sa.Column("usage_record_id", GUID(), nullable=True),
        sa.Column(
            "created_at", UtcDateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("message_id", name="uq_billable_events_message"),
    )
    op.create_index(
        "ix_billable_events_company_occurred", "billable_events", ["company_id", "occurred_at"]
    )
    op.create_index("ix_billable_events_period", "billable_events", ["billing_period_id"])
    op.create_index(
        "ix_billable_events_channel",
        "billable_events",
        ["company_id", "channel_type", "occurred_at"],
    )

    op.create_table(
        "pricing_rate_tiers",
        sa.Column("id", GUID(), primary_key=True),
        # CASCADE: a tier has no meaning without its rate, and pricing_rates
        # is itself append-only, so the parent is never actually deleted in
        # production — this only keeps a development reset honest.
        sa.Column(
            "pricing_rate_id",
            GUID(),
            sa.ForeignKey("pricing_rates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # NULL is the open-ended top step. Genuinely open-ended rather than a
        # very large number, because a very large number is a number somebody
        # eventually exceeds.
        sa.Column("up_to", _AMOUNT, nullable=True),
        sa.Column("unit_amount", _AMOUNT, nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", UtcDateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("unit_amount >= 0", name="ck_pricing_rate_tiers_amount"),
        sa.CheckConstraint("up_to IS NULL OR up_to > 0", name="ck_pricing_rate_tiers_bound"),
        sa.UniqueConstraint(
            "pricing_rate_id", "sort_order", name="uq_pricing_rate_tiers_order"
        ),
    )
    op.create_index("ix_pricing_rate_tiers_rate", "pricing_rate_tiers", ["pricing_rate_id"])

    # Which tier produced the rate on a frozen line. Nullable: lines written
    # before this release were priced flat.
    op.add_column(
        "usage_period_lines", sa.Column("tier_up_to", _AMOUNT, nullable=True)
    )

    _seed_message_rates()

    if op.get_bind().dialect.name != "postgresql":
        return

    # Append-only, like the ledger and the financial audit trail. A billable
    # event is the record of what was charged; a correction is a new
    # adjustment, never an edit.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION billable_events_immutable()
        RETURNS TRIGGER AS $$
        BEGIN
          RAISE EXCEPTION
            'billable_events is append-only: a billable message is a fact, and a '
            'correction is a new adjustment rather than an edit';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_billable_events_immutable
        BEFORE UPDATE OR DELETE ON billable_events
        FOR EACH ROW EXECUTE FUNCTION billable_events_immutable()
        """
    )


def _seed_message_rates() -> None:
    """Global rates for ``BILLABLE_MESSAGE``, one per currency, each tiered.

    Seeded here rather than left to an operator because retiring the
    conversation meter without a message price would stop billing entirely — a
    revenue outage nobody would notice until the month closed unpriced.
    Operators can still override per company or per profile in the console;
    this only guarantees there is always a global answer.

    Ids are computed in Python rather than by ``gen_random_uuid()``: it keeps
    the statement identical on every backend, and a deterministic id makes a
    re-run a no-op instead of a second set of rates.
    """
    bind = op.get_bind()
    metadata = sa.MetaData()
    rates = sa.Table("pricing_rates", metadata, autoload_with=bind)
    tiers = sa.Table("pricing_rate_tiers", metadata, autoload_with=bind)

    for currency, index in (("USD", 1), ("JOD", 2)):
        rate_id = _seeded_id(currency)
        existing = bind.execute(
            sa.select(rates.c.id).where(
                rates.c.scope == "GLOBAL",
                rates.c.metric_code == "BILLABLE_MESSAGE",
                rates.c.currency == currency,
            )
        ).first()
        if existing is not None:
            continue

        # ``unit_amount`` on the parent stays meaningful: it is what the top
        # tier charges, so anything reading a rate without its tiers still gets
        # a correct — if less specific — answer.
        bind.execute(
            rates.insert().values(
                id=rate_id,
                scope="GLOBAL",
                metric_code="BILLABLE_MESSAGE",
                company_id=None,
                profile_id=None,
                unit_amount=Decimal(_TIERS[-1][index]),
                currency=currency,
                effective_from=_EPOCH,
                effective_until=None,
                created_by_user_id=None,
                reason="Seeded with the message-based billing model",
            )
        )
        for order, tier in enumerate(_TIERS, start=1):
            bind.execute(
                tiers.insert().values(
                    id=_seeded_id(f"{currency}:{order}"),
                    pricing_rate_id=rate_id,
                    up_to=Decimal(tier[0]) if tier[0] is not None else None,
                    unit_amount=Decimal(tier[index]),
                    sort_order=order,
                )
            )


def _seeded_id(seed: str) -> uuid.UUID:
    """A stable id, so re-running this migration cannot double-seed."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"blinkengage:billable-message-rate:{seed}")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_billable_events_immutable ON billable_events")
        op.execute("DROP FUNCTION IF EXISTS billable_events_immutable()")

    bind = op.get_bind()
    metadata = sa.MetaData()
    rates = sa.Table("pricing_rates", metadata, autoload_with=bind)
    bind.execute(rates.delete().where(rates.c.metric_code == "BILLABLE_MESSAGE"))

    op.drop_column("usage_period_lines", "tier_up_to")
    op.drop_index("ix_pricing_rate_tiers_rate", table_name="pricing_rate_tiers")
    op.drop_table("pricing_rate_tiers")
    op.drop_index("ix_billable_events_channel", table_name="billable_events")
    op.drop_index("ix_billable_events_period", table_name="billable_events")
    op.drop_index("ix_billable_events_company_occurred", table_name="billable_events")
    op.drop_table("billable_events")
