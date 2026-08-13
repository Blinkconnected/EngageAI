"""Readers for the five document kinds this phase supports.

Every one of these opens a file somebody else wrote. The rules they all follow:

- **No network.** There is no HTTP client in this module and no way to reach
  one. A DOCX referencing a remote image gets the reference dropped, not
  fetched.
- **No runtime.** DOCX and XLSX are ZIP archives of XML, and that is how they
  are read. No office application is invoked, so a macro has nothing to run
  in — ``openpyxl`` never evaluates VBA, and ``keep_vba`` is deliberately not
  passed.
- **No formulas evaluated.** ``data_only=True`` reads the cached value a
  spreadsheet stored, never the expression. An unevaluated formula reads as
  empty rather than as something this process computed.
- **Caps inside the loop.** The generic checks bound the file; only the parser
  knows what a page is, so each stops itself.

OCR is absent on purpose. A PDF with no text layer is refused with
``NO_TEXT_LAYER``; an OCR parser would register here for that case later.
"""

from __future__ import annotations

import csv
import io
from importlib.metadata import PackageNotFoundError, version

from blinkengage.domain.brain.document_parser import ExtractedDocument
from blinkengage.domain.brain.documents import (
    MAX_CSV_ROWS,
    MAX_PDF_PAGES,
    MAX_XLSX_ROWS,
    MAX_XLSX_SHEETS,
    DocumentKind,
    DocumentRejected,
    DocumentRejection,
    check_archive_safety,
    truncate,
)


def _installed(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:  # pragma: no cover - packaging accident
        return "unknown"


class PdfParser:
    """Text layer only. A scan is a refusal, not an empty document."""

    kind = DocumentKind.PDF
    name = "pypdf"

    def extract(self, data: bytes) -> ExtractedDocument:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        try:
            reader = PdfReader(io.BytesIO(data))
        except PdfReadError as exc:
            raise DocumentRejected(DocumentRejection.CORRUPT, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - hostile input, any failure is a refusal
            raise DocumentRejected(DocumentRejection.CORRUPT, str(exc)) from exc

        if reader.is_encrypted:
            # Fails closed. pypdf would try an empty password, which either
            # silently half-works or produces gibberish, and there is nobody
            # here to ask for the real one.
            raise DocumentRejected(
                DocumentRejection.ENCRYPTED, "the document is password-protected"
            )

        try:
            pages = reader.pages
            total = len(pages)
        except Exception as exc:  # noqa: BLE001
            raise DocumentRejected(DocumentRejection.CORRUPT, str(exc)) from exc

        read = min(total, MAX_PDF_PAGES)
        chunks: list[str] = []
        for index in range(read):
            try:
                chunks.append(pages[index].extract_text() or "")
            except Exception:  # noqa: BLE001 - one bad page must not lose the rest
                continue

        text = "\n".join(chunk for chunk in chunks if chunk).strip()
        if not text:
            # Pages exist and none of them carry text: a scan. Refusing is the
            # point — half-reading a price list fails invisibly, and an empty
            # string is indistinguishable from a document that said nothing.
            raise DocumentRejected(
                DocumentRejection.NO_TEXT_LAYER,
                f"{total} page(s) with no extractable text layer",
            )

        return ExtractedDocument(
            text=truncate(text),
            parser=self.name,
            parser_version=_installed("pypdf"),
            units_read=read,
            truncated=read < total,
            metadata={"pages": str(total)},
        )


class DocxParser:
    """Paragraphs and table cells. No macros, no runtime, no remote parts."""

    kind = DocumentKind.DOCX
    name = "python-docx"

    def extract(self, data: bytes) -> ExtractedDocument:
        import docx

        check_archive_safety(data)
        try:
            document = docx.Document(io.BytesIO(data))
        except Exception as exc:  # noqa: BLE001
            raise DocumentRejected(DocumentRejection.CORRUPT, str(exc)) from exc

        lines = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
        # Tables carry the prices in most real price lists, and a paragraph
        # walk alone silently misses every one of them.
        for table in document.tables:
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                if any(cells):
                    lines.append("\t".join(cells))

        text = "\n".join(lines).strip()
        if not text:
            raise DocumentRejected(DocumentRejection.EMPTY, "no text in the document")

        return ExtractedDocument(
            text=truncate(text),
            parser=self.name,
            parser_version=_installed("python-docx"),
            units_read=len(lines),
        )


class XlsxParser:
    """Cached cell values. Formulas are never evaluated."""

    kind = DocumentKind.XLSX
    name = "openpyxl"

    def extract(self, data: bytes) -> ExtractedDocument:
        from openpyxl import load_workbook

        check_archive_safety(data)
        try:
            workbook = load_workbook(
                io.BytesIO(data),
                # The stored value, never the expression. Evaluating a
                # workbook's formulas would mean running somebody else's
                # arithmetic in this process.
                data_only=True,
                # Streaming, so a wide sheet is not materialised to read its
                # first rows.
                read_only=True,
            )
        except Exception as exc:  # noqa: BLE001
            raise DocumentRejected(DocumentRejection.CORRUPT, str(exc)) from exc

        lines: list[str] = []
        rows_read = 0
        truncated = False
        try:
            for sheet_index, sheet in enumerate(workbook.worksheets):
                if sheet_index >= MAX_XLSX_SHEETS:
                    truncated = True
                    break
                lines.append(f"# {sheet.title}")
                for row in sheet.iter_rows(values_only=True):
                    if rows_read >= MAX_XLSX_ROWS:
                        truncated = True
                        break
                    cells = [str(value) for value in row if value is not None]
                    if cells:
                        lines.append("\t".join(cells))
                    rows_read += 1
                if truncated:
                    break
        except Exception as exc:  # noqa: BLE001
            raise DocumentRejected(DocumentRejection.CORRUPT, str(exc)) from exc
        finally:
            workbook.close()

        text = "\n".join(lines).strip()
        if not text or all(line.startswith("# ") for line in lines):
            raise DocumentRejected(DocumentRejection.EMPTY, "no cell values")

        return ExtractedDocument(
            text=truncate(text),
            parser=self.name,
            parser_version=_installed("openpyxl"),
            units_read=rows_read,
            truncated=truncated,
        )


class CsvParser:
    """Delimited text, read as text. Never as a spreadsheet.

    Worth stating because it is a real vulnerability elsewhere: a cell
    beginning ``=`` is a formula to Excel and is a string here. Nothing in
    this path evaluates it, and nothing writes it back out to a file that
    something else would open.
    """

    kind = DocumentKind.CSV
    name = "csv"

    def extract(self, data: bytes) -> ExtractedDocument:
        text = _decode(data)
        lines: list[str] = []
        truncated = False
        reader = csv.reader(io.StringIO(text))
        try:
            for index, row in enumerate(reader):
                if index >= MAX_CSV_ROWS:
                    truncated = True
                    break
                cells = [cell.strip() for cell in row if cell.strip()]
                if cells:
                    lines.append("\t".join(cells))
        except csv.Error as exc:
            raise DocumentRejected(DocumentRejection.CORRUPT, str(exc)) from exc

        joined = "\n".join(lines).strip()
        if not joined:
            raise DocumentRejected(DocumentRejection.EMPTY, "no rows")

        return ExtractedDocument(
            text=truncate(joined),
            parser=self.name,
            parser_version="stdlib",
            units_read=len(lines),
            truncated=truncated,
        )


class TxtParser:
    kind = DocumentKind.TXT
    name = "text"

    def extract(self, data: bytes) -> ExtractedDocument:
        text = _decode(data).strip()
        if not text:
            raise DocumentRejected(DocumentRejection.EMPTY, "no text")
        return ExtractedDocument(
            text=truncate(text),
            parser=self.name,
            parser_version="stdlib",
            units_read=text.count("\n") + 1,
        )


def _decode(data: bytes) -> str:
    """UTF-8, then latin-1 as a last resort.

    ``errors="replace"`` rather than a failure: a stray byte in an otherwise
    readable price list should cost that character, not the document. A file
    that is genuinely not text never reaches here — ``sniff`` refuses it.
    """
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace")


#: The registry the pipeline resolves through. An OCR parser is added here and
#: nowhere else.
_PARSERS: dict[DocumentKind, object] = {
    DocumentKind.PDF: PdfParser(),
    DocumentKind.DOCX: DocxParser(),
    DocumentKind.XLSX: XlsxParser(),
    DocumentKind.CSV: CsvParser(),
    DocumentKind.TXT: TxtParser(),
}


def resolve_parser(kind: DocumentKind) -> object | None:
    """The parser for a kind, or ``None`` when nothing can read it."""
    return _PARSERS.get(kind)


__all__ = [
    "CsvParser",
    "DocxParser",
    "PdfParser",
    "TxtParser",
    "XlsxParser",
    "resolve_parser",
]
