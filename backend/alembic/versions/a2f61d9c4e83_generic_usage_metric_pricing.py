"""pricing models on a rate: flat, tiered, and room for the rest

See ``docs/architecture/billing.md``.

A rate used to be a number and, since the last release, an optional tier
table. Neither survives the metrics this product will bill: tokens are sold in
graduated ladders, storage in packages, seats as a fixed monthly fee, phone
minutes with a commitment and overage beyond it.

So *how* a rate charges becomes data on the rate:

- ``pricing_model`` — which model applies. Only ``flat`` and ``volume_tier``
  may be written today; the rest are declared in
  ``domain/pricing_models.py`` and refused at the boundary, so the schema and
  the console are designed against the whole shape once.
- ``included_quantity`` — units that cost nothing this period. Was a constant
  in ``domain/allowances.py``, keyed by metric; now a property of the rate,
  which is where "the first 100 are free" actually belongs — it varies by
  plan, by negotiation and by currency. The code table remains the default for
  a rate that does not set one, so nothing changes for a rate written before
  this.
- ``minimum_charge`` — a floor under the line's subtotal.
- ``model_params`` — parameters whose shape depends on the model (package
  size, committed quantity, overage rate). JSON rather than a nullable column
  per future model, because that would be five columns that are NULL forever
  and a sixth the day somebody invents another model.

``usage_period_lines.pricing_model`` records which model produced a frozen
line, so an invoice can answer "why is this the amount?" years later without
re-deriving it from a rate that has since changed.

**Two planned metric codes are renamed** to match the product's naming:
``VOICE_MINUTE`` → ``PHONE_MINUTE`` and ``STORAGE_GB`` → ``STORAGE_GB_MONTH``.
Renaming a metric code is normally forbidden — codes appear on invoices and in
pricing history — but both were ``PLANNED``: never metered, and refused by the
pricing API, so no rate, usage record, snapshot line or invoice can reference
them. This migration asserts exactly that before renaming, and fails rather
than guessing if some deployment proves otherwise.

Revision ID: a2f61d9c4e83
Revises: e8c3f47a1b60
Create Date: 2026-07-30 18:10:00.000000
"""

from collections.abc import Sequence
from decimal import Decimal

import sqlalchemy as sa

from alembic import op

revision: str = "a2f61d9c4e83"
down_revision: str | Sequence[str] | None = "e8c3f47a1b60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AMOUNT = sa.Numeric(18, 6)

#: The metric that ships metered, and the allowance it has always had. Written
#: onto its rates so the free quantity becomes a property of the price rather
#: than a constant in code — with the same number, so nothing changes.
_MESSAGE_METRIC = "BILLABLE_MESSAGE"
_MESSAGE_ALLOWANCE = Decimal(100)

#: Renamed planned metrics: (old, new).
_RENAMED: tuple[tuple[str, str], ...] = (
    ("VOICE_MINUTE", "PHONE_MINUTE"),
    ("STORAGE_GB", "STORAGE_GB_MONTH"),
)


def upgrade() -> None:
    op.add_column(
        "pricing_rates",
        sa.Column(
            "pricing_model",
            sa.String(20),
            nullable=False,
            server_default="FLAT",
        ),
    )
    op.add_column("pricing_rates", sa.Column("included_quantity", _AMOUNT, nullable=True))
    op.add_column("pricing_rates", sa.Column("minimum_charge", _AMOUNT, nullable=True))
    op.add_column(
        "pricing_rates",
        sa.Column("model_params", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.create_check_constraint(
        "ck_pricing_rates_included_non_negative",
        "pricing_rates",
        "included_quantity IS NULL OR included_quantity >= 0",
    )
    op.create_check_constraint(
        "ck_pricing_rates_minimum_non_negative",
        "pricing_rates",
        "minimum_charge IS NULL OR minimum_charge >= 0",
    )

    op.add_column(
        "usage_period_lines",
        sa.Column("pricing_model", sa.String(20), nullable=False, server_default="FLAT"),
    )

    bind = op.get_bind()

    # Every rate that carries a tier table is a volume-tier rate; that is what
    # a table has meant since tiers shipped. Stated as a data change rather
    # than left to a default, because "flat rate with a tier table" is a state
    # the new validation refuses.
    bind.execute(
        sa.text(
            """
            UPDATE pricing_rates SET pricing_model = 'VOLUME_TIER'
            WHERE id IN (SELECT DISTINCT pricing_rate_id FROM pricing_rate_tiers)
            """
        )
    )

    # The message allowance moves from code to data, unchanged in value.
    bind.execute(
        sa.text(
            "UPDATE pricing_rates SET included_quantity = :allowance "
            "WHERE metric_code = :metric AND included_quantity IS NULL"
        ),
        {"allowance": _MESSAGE_ALLOWANCE, "metric": _MESSAGE_METRIC},
    )

    _rename_planned_metrics(bind)


def _rename_planned_metrics(bind: sa.engine.Connection) -> None:
    """Renames two never-metered codes, refusing if anything references them.

    A metric code is a stable public identifier precisely because invoices and
    pricing history quote it. These two were PLANNED — unmeterable and
    unpriceable by construction — so nothing *can* reference them. Asserted
    rather than assumed: if a deployment somehow has such a row, stopping is
    right and a silent rename is not.
    """
    for old, _new in _RENAMED:
        for table, column in (
            ("pricing_rates", "metric_code"),
            ("usage_records", "metric_code"),
            ("usage_period_lines", "metric_code"),
            ("invoice_lines", "metric_code"),
        ):
            count = bind.execute(
                sa.text(f"SELECT count(*) FROM {table} WHERE {column} = :code"),  # noqa: S608
                {"code": old},
            ).scalar_one()
            if count:
                raise RuntimeError(
                    f"{count} row(s) in {table} reference the metric {old!r}, which "
                    "this migration was about to rename on the assumption that it "
                    "was never priced or metered. Renaming it would silently "
                    "reprice history; resolve those rows first."
                )


def downgrade() -> None:
    op.drop_column("usage_period_lines", "pricing_model")
    op.drop_constraint("ck_pricing_rates_minimum_non_negative", "pricing_rates")
    op.drop_constraint("ck_pricing_rates_included_non_negative", "pricing_rates")
    op.drop_column("pricing_rates", "model_params")
    op.drop_column("pricing_rates", "minimum_charge")
    op.drop_column("pricing_rates", "included_quantity")
    op.drop_column("pricing_rates", "pricing_model")
