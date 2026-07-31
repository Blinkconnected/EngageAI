"""Renderers for the financial documents Blink Engage sends out.

Separate from ``infrastructure/reporting`` on purpose. A report is a table
a tenant asked for and can regenerate at will; an invoice is a numbered
commercial document whose content is frozen, and the two have different
rules about what may change between two renders of the same thing.
"""

from blinkengage.infrastructure.documents.invoice_pdf import render_invoice_pdf

__all__ = ["render_invoice_pdf"]
