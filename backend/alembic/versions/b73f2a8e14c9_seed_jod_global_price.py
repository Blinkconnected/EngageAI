"""seed the JOD global conversation price

See ``docs/architecture/billing.md``.

A rate is priced *in a currency*, and pricing resolution only considers
rates in the company's own currency — so without a JOD global default,
every Jordanian company would resolve nothing and close its month with an
``unpriced`` line. That is the correct, visible failure the usage engine
already reports, and this is the fix for it: a price to resolve.

0.035 JOD per conversation, from the pricing epoch. Set deliberately
rather than converted from the dollar price: this build stores no exchange
rate, and a price derived from one would drift the moment the rate moved
while the invoice it produced would claim to be exact. An operator can
change it from the console like any other price, and the change is
audited and effective-dated like any other.

Note the **three** decimal places. JOD settles in fils, and a price
carried at two would round 0.035 to 0.04 — a 14% error on every
conversation.

Revision ID: b73f2a8e14c9
Revises: a1c6e93d5f28
Create Date: 2026-07-29 23:10:00.000000
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

import sqlalchemy as sa
from alembic import op

revision: str = "b73f2a8e14c9"
down_revision: str | None = "a1c6e93d5f28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The same instant the dollar global price starts from, so the two
#: timelines line up and neither has a period it does not cover.
#: Matches ``domain/pricing.PRICING_EPOCH``.
_PRICING_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_JOD_CONVERSATION_PRICE = Decimal("0.035000")


def upgrade() -> None:
    # The overlap constraint predates currencies: it forbids two live
    # rates for the same (metric, company, profile) over the same window,
    # which now wrongly forbids a dollar price and a dinar price coexisting
    # for the same metric. Currency is part of a rate's identity, so it
    # belongs in the constraint — without this, adding a second currency
    # is impossible rather than merely unpriced.
    op.execute("ALTER TABLE pricing_rates DROP CONSTRAINT ex_pricing_rates_no_overlap")
    op.execute(
        """
        ALTER TABLE pricing_rates ADD CONSTRAINT ex_pricing_rates_no_overlap
        EXCLUDE USING gist (
            metric_code WITH =,
            currency WITH =,
            COALESCE(company_id, '00000000-0000-0000-0000-000000000000'::uuid) WITH =,
            COALESCE(profile_id, '00000000-0000-0000-0000-000000000000'::uuid) WITH =,
            tstzrange(effective_from, effective_until, '[)') WITH &&
        ) WHERE (voided_at IS NULL)
        """
    )

    connection = op.get_bind()
    existing = connection.execute(
        sa.text(
            "SELECT 1 FROM pricing_rates WHERE scope = 'GLOBAL' "
            "AND metric_code = 'CONVERSATION' AND currency = 'JOD' LIMIT 1"
        )
    ).first()
    if existing is not None:
        return

    connection.execute(
        sa.text(
            """
            INSERT INTO pricing_rates (
                id, scope, metric_code, company_id, profile_id, unit_amount,
                currency, effective_from, effective_until, created_at,
                created_by_email, reason
            ) VALUES (
                :id, 'GLOBAL', 'CONVERSATION', NULL, NULL, :amount,
                'JOD', :epoch, NULL, now(), NULL,
                'Initial JOD global default for Jordanian companies'
            )
            """
        ),
        {
            "id": uuid.uuid4(),
            "amount": _JOD_CONVERSATION_PRICE,
            "epoch": _PRICING_EPOCH,
        },
    )


def downgrade() -> None:
    op.execute("ALTER TABLE pricing_rates DROP CONSTRAINT ex_pricing_rates_no_overlap")
    op.execute(
        """
        ALTER TABLE pricing_rates ADD CONSTRAINT ex_pricing_rates_no_overlap
        EXCLUDE USING gist (
            metric_code WITH =,
            COALESCE(company_id, '00000000-0000-0000-0000-000000000000'::uuid) WITH =,
            COALESCE(profile_id, '00000000-0000-0000-0000-000000000000'::uuid) WITH =,
            tstzrange(effective_from, effective_until, '[)') WITH &&
        ) WHERE (voided_at IS NULL)
        """
    )
    op.execute(
        "DELETE FROM pricing_rates WHERE scope = 'GLOBAL' "
        "AND metric_code = 'CONVERSATION' AND currency = 'JOD'"
    )
