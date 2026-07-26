"""``ErpClient`` — the plugin contract for the ERPNext integration. See
``docs/architecture/erp-integration.md``.

A ``Protocol``, not an ``ABC`` — deliberately unlike ``ChannelProvider``/
``AiProvider``/``SmsGateway``, which need named registry-based lookup
from a plain config string (many interchangeable providers behind one
config value). ERPNext is the one named ERP integration this milestone
builds (CLAUDE.md's ERP section names only ERPNext, not a plugin
architecture the way channels/AI/SMS explicitly are) — there is exactly
one concrete implementation, constructed directly from an ``ErpConfig``
row, so a registry would be pure ceremony with nothing to register a
second entry against.

Deliberately minimal: creating a customer record is the only typed
operation every sync path needs. Reading back invoices/orders/quotations/
tickets/payments is intentionally *not* one method per document type —
those are heterogeneous, read-only, per-company-customized document
shapes best handled generically (see ``list_records``), not modeled as
first-class domain types this platform would need to keep in lockstep
with every customer's ERPNext customizations.
"""

from typing import Any, Protocol


class ErpClient(Protocol):
    async def create_customer(self, *, name: str, email: str | None, phone: str | None) -> str:
        """Creates (or is a no-op idempotent proxy for) a Customer
        document in ERPNext. Returns ERPNext's document name — the
        identifier future reads/lookups are keyed on."""
        ...

    async def list_records(self, *, doctype: str, customer_name: str) -> list[dict[str, Any]]:
        """Best-effort generic read: ``GET /api/resource/<doctype>``
        filtered to records referencing ``customer_name``. Not every
        ERPNext doctype uses the same field name for "which customer
        this belongs to" — see ``infrastructure/erp/client.py`` for the
        known limitation this implies."""
        ...

    async def health_check(self) -> tuple[bool, str | None]:
        """Returns ``(healthy, detail)`` — ``detail`` is a human-readable
        failure reason when ``healthy`` is ``False`` (surfaced by "Test
        Connection"), ``None`` when healthy."""
        ...
