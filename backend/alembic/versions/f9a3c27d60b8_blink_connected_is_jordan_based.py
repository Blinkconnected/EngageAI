"""the Blink Connected tenant is Jordan based

See ``docs/architecture/billing.md``.

Blink Connected is our own tenant, and it is in Jordan. It was created
before countries existed, so it carries no country and the rest-of-world
default currency — which means it is offered PayPal rather than Jordan's
domestic ``bill_reference`` route, and would be billed in dollars.

**This is the one thing the domain says is fixed.** A company's country
is chosen at signup and then left alone, because it decides the currency
and re-denominating issued invoices and ledger entries is never safe. The
exception is not that this tenant is ours; it is that after
``scripts/reset_company_billing.sql`` has run there are no documents left
in the old currency, so nothing is being re-denominated. That ordering is
enforced rather than remembered: the guard below refuses to run while any
dollar-denominated record of this company still exists, and names the
script to run first. A migration that quietly relabelled a $5.00 credit
balance as JD 5.000 is exactly the failure the fixed-currency rule
exists to prevent.

Keyed to one company id, so in any database that does not contain it —
every other installation, and every freshly created one — this is a
no-op. It is deliberately *not* a general "change a company's country"
facility: there is no such thing, on purpose.

Nothing here deletes anything. Erasing financial records needs the
immutability triggers disabled, and that belongs in a named
development/staging script, never in something a deploy runs.

The JOD global conversation price seeded in ``b73f2a8e14c9`` is already in
place by the time this runs, so the tenant is priceable in dinars the
moment it switches and does not close its month with an ``unpriced``
line.

Revision ID: f9a3c27d60b8
Revises: d4a71b58c02e
Create Date: 2026-07-30 09:55:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f9a3c27d60b8"
down_revision: str | None = "d4a71b58c02e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Blink Connected (slug ``blink-demo``) — our own tenant.
_COMPANY_ID = "12c81f88-2652-419e-9741-07bb59602a82"

_COUNTRY = "JO"
#: Not read from ``domain/countries.py``: a migration states the value it
#: wrote. If Jordan's currency were ever edited in the domain, history
#: must not silently change to match — see the same reasoning on
#: ``Company.billing_currency``.
_CURRENCY = "JOD"

#: Every table that carries a currency of its own and would be left
#: stating dollars for a dinar company. Checked before the switch, not
#: after, because the point is to refuse rather than to report.
_DENOMINATED: tuple[tuple[str, str], ...] = (
    ("invoices", "SELECT count(*) FROM invoices WHERE company_id = :id AND currency <> :currency"),
    (
        "credit_notes",
        "SELECT count(*) FROM credit_notes WHERE company_id = :id AND currency <> :currency",
    ),
    ("payments", "SELECT count(*) FROM payments WHERE company_id = :id AND currency <> :currency"),
    (
        "payment_intents",
        "SELECT count(*) FROM payment_intents WHERE company_id = :id AND currency <> :currency",
    ),
    (
        "payment_refunds",
        "SELECT count(*) FROM payment_refunds WHERE company_id = :id AND currency <> :currency",
    ),
    (
        "ledger_entries",
        "SELECT count(*) FROM ledger_entries WHERE company_id = :id AND currency <> :currency",
    ),
    (
        "financial_audit_events",
        "SELECT count(*) FROM financial_audit_events "
        "WHERE company_id = :id AND currency IS NOT NULL AND currency <> :currency",
    ),
    (
        "billing_periods",
        "SELECT count(*) FROM billing_periods WHERE company_id = :id AND currency <> :currency",
    ),
    (
        "billing_daily_summary",
        "SELECT count(*) FROM billing_daily_summary "
        "WHERE company_id = :id AND currency <> :currency",
    ),
    (
        "usage_period_lines",
        "SELECT count(*) FROM usage_period_lines upl "
        "JOIN billing_periods bp ON bp.id = upl.billing_period_id "
        "WHERE bp.company_id = :id AND upl.currency <> :currency",
    ),
)


def upgrade() -> None:
    connection = op.get_bind()
    params = {"id": _COMPANY_ID, "currency": _CURRENCY}

    current = connection.execute(
        sa.text("SELECT country_code, billing_currency FROM companies WHERE id = :id"),
        {"id": _COMPANY_ID},
    ).first()
    if current is None:
        # Any installation other than ours. Nothing to correct.
        return
    if current[0] == _COUNTRY and current[1] == _CURRENCY:
        # Already done — re-running a migration must not be the thing that
        # breaks, and the guard below would be answering a question that
        # has already been settled.
        return

    residue = {
        table: connection.execute(sa.text(query), params).scalar_one()
        for table, query in _DENOMINATED
    }
    remaining = {table: count for table, count in residue.items() if count}
    if remaining:
        detail = ", ".join(f"{table}: {count}" for table, count in sorted(remaining.items()))
        raise RuntimeError(
            f"Company {_COMPANY_ID} still holds records denominated in another "
            f"currency ({detail}). Refusing to change its billing currency to "
            f"{_CURRENCY}: those documents state an amount in the currency they "
            "were issued in, and a company switched underneath them would have "
            "its balances presented in a currency they are not in. Run "
            "scripts/reset_company_billing.sql for this company first, then "
            "re-run this migration."
        )

    connection.execute(
        sa.text(
            "UPDATE companies SET country_code = :country, billing_currency = :currency "
            "WHERE id = :id"
        ),
        {"country": _COUNTRY, "currency": _CURRENCY, "id": _COMPANY_ID},
    )


def downgrade() -> None:
    # Back to "no country recorded", which is the honest previous value —
    # this tenant genuinely had none — and the rest-of-world currency it
    # was on. Only the columns: the documents removed by the reset script
    # are not this migration's to restore, and a downgrade that appeared
    # to bring back invoices it never deleted would be worse than one that
    # says nothing about them.
    op.get_bind().execute(
        sa.text(
            "UPDATE companies SET country_code = NULL, billing_currency = 'USD' "
            "WHERE id = :id AND billing_currency = :currency"
        ),
        {"id": _COMPANY_ID, "currency": _CURRENCY},
    )
