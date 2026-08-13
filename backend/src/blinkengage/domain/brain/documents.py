"""What a document is, decided from its bytes, and what may be done to it.

Every rule here is a refusal, and the refusals are the feature. A document
arriving by email is the most hostile input a business system takes: it is
authored by somebody outside the company, it is opened by a parser written to
be permissive, and the thing that reads it afterwards will treat whatever came
out as company knowledge.

Three principles, in the order they matter:

**The extension is a claim, not a fact.** ``pricing.pdf`` naming a ZIP is the
oldest trick there is. The kind is sniffed from the leading bytes, and a file
whose content does not match anything supported is refused rather than guessed
at.

**Limits are enforced before parsing, not during.** A 40 KB ZIP that expands to
6 GB costs nothing to reject by reading its central directory, and costs the
worker to discover halfway through. The size cap, the compression-ratio check
and the page/sheet/row caps all run ahead of the expensive work.

**Half-read is worse than refused.** A scanned PDF with no text layer yields an
empty string, which looks exactly like a document that had nothing to say —
and a price list that silently contributed nothing is a failure nobody
notices. It is a terminal rejection with a stated reason, and OCR is a later
phase that registers a parser rather than changing this rule.
"""

from __future__ import annotations

import zipfile
from enum import StrEnum
from io import BytesIO

#: Nothing larger is read. Well under the 25 MiB customer-attachment ceiling
#: on purpose: a company price list is a document, and something that size
#: arriving at a knowledge mailbox is more likely a mistake than a policy.
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024

#: Caps applied before the parser runs.
MAX_PDF_PAGES = 300
MAX_XLSX_SHEETS = 50
MAX_XLSX_ROWS = 20_000
MAX_CSV_ROWS = 50_000
#: Extracted text is truncated rather than refused past this: the first
#: megabyte of a price list is the price list, and an unbounded string is a
#: memory footprint an attacker chooses.
MAX_EXTRACTED_CHARS = 1_000_000

#: A ZIP whose contents expand by more than this is treated as hostile. Real
#: office documents are XML and compress well — 20× is comfortably above what
#: a genuine DOCX or XLSX reaches, and far below what a bomb needs.
MAX_COMPRESSION_RATIO = 200
#: Absolute ceiling on the sum of the declared uncompressed sizes.
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024


class DocumentKind(StrEnum):
    """The kinds this phase can read. OCR would add one, not change these."""

    PDF = "PDF"
    DOCX = "DOCX"
    XLSX = "XLSX"
    CSV = "CSV"
    TXT = "TXT"


class DocumentRejection(StrEnum):
    """Why a document produced no text. Every one is terminal.

    Terminal because none of them get better on a retry: a scanned PDF is
    scanned on the second attempt too. Transient failures belong to the job
    state machine (4D) and are deliberately not in this vocabulary.
    """

    #: The bytes match nothing supported. Includes a file whose extension
    #: claims one thing and whose content is another.
    UNSUPPORTED_TYPE = "UNSUPPORTED_TYPE"
    TOO_LARGE = "TOO_LARGE"
    #: Password-protected. Fails closed — the alternative is prompting, and
    #: there is nobody to prompt.
    ENCRYPTED = "ENCRYPTED"
    #: A PDF with pages and no text layer. Almost always a scan.
    NO_TEXT_LAYER = "NO_TEXT_LAYER"
    #: Structurally broken: truncated, not the container it claims, unreadable.
    CORRUPT = "CORRUPT"
    #: A ZIP that expands far beyond its size, or declares more content than
    #: any real document holds.
    ARCHIVE_BOMB = "ARCHIVE_BOMB"
    #: Within limits, parsed cleanly, and contained no text at all.
    EMPTY = "EMPTY"


class DocumentRejected(Exception):
    """A document that will not be read, and why."""

    def __init__(self, reason: DocumentRejection, detail: str = "") -> None:
        super().__init__(detail or reason.value)
        self.reason = reason
        self.detail = detail


#: Leading bytes, longest first so a longer signature is never shadowed by a
#: shorter prefix of itself.
_SIGNATURES: tuple[tuple[bytes, DocumentKind], ...] = (
    (b"%PDF-", DocumentKind.PDF),
    # OOXML is a ZIP. Which OOXML it is cannot be told from the signature and
    # is resolved by looking inside — see ``_ooxml_kind``.
    (b"PK\x03\x04", DocumentKind.DOCX),
)


def _ooxml_kind(data: bytes) -> DocumentKind | None:
    """DOCX or XLSX, by what the archive actually contains.

    By member name rather than by ``[Content_Types].xml``, because the parts
    are what the parser will read: an archive claiming to be a workbook with
    no ``xl/`` in it is not a workbook, whatever its manifest says.
    """
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            names = archive.namelist()
    except (zipfile.BadZipFile, OSError):
        return None
    if any(name.startswith("word/") for name in names):
        return DocumentKind.DOCX
    if any(name.startswith("xl/") for name in names):
        return DocumentKind.XLSX
    return None


def _is_probably_text(data: bytes) -> bool:
    """Decodable as UTF-8 and free of control bytes that text does not carry."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return "\x00" not in text


def sniff(data: bytes, *, filename: str | None = None) -> DocumentKind | None:
    """The kind, from the content. ``None`` when nothing supported matches.

    ``filename`` is consulted for exactly one thing — telling CSV from plain
    text, which are the same bytes and differ only in how they are read. It
    can never *promote* a file: a ``.pdf`` whose content is a ZIP is read as
    the ZIP, and a ``.csv`` full of PDF bytes is a PDF.
    """
    for signature, kind in _SIGNATURES:
        if data.startswith(signature):
            if kind is DocumentKind.DOCX:
                return _ooxml_kind(data)
            return kind

    if _is_probably_text(data):
        suffix = (filename or "").rsplit(".", 1)[-1].lower()
        return DocumentKind.CSV if suffix == "csv" else DocumentKind.TXT
    return None


def check_size(data: bytes) -> None:
    """Refuse anything oversized before a parser is chosen."""
    if len(data) > MAX_DOCUMENT_BYTES:
        raise DocumentRejected(
            DocumentRejection.TOO_LARGE,
            f"{len(data)} bytes exceeds the {MAX_DOCUMENT_BYTES}-byte limit",
        )


def check_archive_safety(data: bytes) -> None:
    """Read the ZIP's own directory and refuse a bomb before opening it.

    The declared sizes are attacker-controlled and that is fine: a bomb has to
    declare its expansion to be unpacked, so a liar here produces a truncated
    read rather than an exhausted host. Both are refusals.
    """
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            total = sum(info.file_size for info in archive.infolist())
    except (zipfile.BadZipFile, OSError) as exc:
        raise DocumentRejected(DocumentRejection.CORRUPT, str(exc)) from exc

    if total > MAX_UNCOMPRESSED_BYTES:
        raise DocumentRejected(
            DocumentRejection.ARCHIVE_BOMB,
            f"declares {total} uncompressed bytes",
        )
    if data and total // max(len(data), 1) > MAX_COMPRESSION_RATIO:
        raise DocumentRejected(
            DocumentRejection.ARCHIVE_BOMB,
            f"expands {total // max(len(data), 1)}x",
        )


def truncate(text: str) -> str:
    """Bound the extracted text. Truncation is not a rejection."""
    return text if len(text) <= MAX_EXTRACTED_CHARS else text[:MAX_EXTRACTED_CHARS]


__all__ = [
    "MAX_COMPRESSION_RATIO",
    "MAX_CSV_ROWS",
    "MAX_DOCUMENT_BYTES",
    "MAX_EXTRACTED_CHARS",
    "MAX_PDF_PAGES",
    "MAX_UNCOMPRESSED_BYTES",
    "MAX_XLSX_ROWS",
    "MAX_XLSX_SHEETS",
    "DocumentKind",
    "DocumentRejected",
    "DocumentRejection",
    "check_archive_safety",
    "check_size",
    "sniff",
    "truncate",
]
