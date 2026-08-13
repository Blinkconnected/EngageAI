"""Readers for untrusted inbound documents.

Deliberately not ``infrastructure/documents``, which *renders* the financial
documents this platform sends out. Writing an invoice and reading a stranger's
PDF are opposite trust positions, and a package that did both would invite one
set of assumptions to be applied to the other.
"""

from blinkengage.infrastructure.document_extraction.parsers import resolve_parser

__all__ = ["resolve_parser"]
