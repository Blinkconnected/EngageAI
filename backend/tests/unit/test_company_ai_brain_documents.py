"""Phase 4C: reading an attachment somebody else wrote.

Every test here is a refusal or a boundary. A document arriving by email is
authored outside the company, opened by a library written to be permissive, and
whatever comes out will later be treated as company knowledge — so the useful
assertions are about what does *not* happen.

The three that matter most:

- **The extension is a claim.** ``pricing.pdf`` containing a ZIP is a ZIP.
- **A scan is refused, not half-read.** An empty extraction from a page full of
  pixels looks exactly like a document that said nothing, and a price list that
  silently contributed nothing is a failure nobody notices.
- **Limits run before parsing.** A 40 KB archive that expands to gigabytes is
  rejected from its own directory listing, not discovered halfway through.
"""

from __future__ import annotations

import ast
import io
import pathlib
import zipfile

import pytest

from blinkengage.domain.brain.documents import (
    MAX_DOCUMENT_BYTES,
    DocumentKind,
    DocumentRejected,
    DocumentRejection,
    check_archive_safety,
    check_size,
    sniff,
    truncate,
)
from blinkengage.infrastructure.document_extraction.parsers import (
    CsvParser,
    DocxParser,
    PdfParser,
    TxtParser,
    XlsxParser,
    resolve_parser,
)

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "blinkengage"


def _zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


# --- sniffing: content, never the name --------------------------------


class TestSniffing:
    def test_a_pdf_is_recognised_by_its_signature(self) -> None:
        assert sniff(b"%PDF-1.7\nrest", filename="anything.txt") is DocumentKind.PDF

    def test_a_zip_pretending_to_be_a_pdf_is_read_as_what_it_is(self) -> None:
        """The oldest trick there is, and the reason extensions are ignored."""
        data = _zip({"word/document.xml": b"<w/>"})

        assert sniff(data, filename="pricing.pdf") is DocumentKind.DOCX

    def test_docx_and_xlsx_are_told_apart_by_their_parts(self) -> None:
        assert sniff(_zip({"word/document.xml": b"<w/>"})) is DocumentKind.DOCX
        assert sniff(_zip({"xl/workbook.xml": b"<x/>"})) is DocumentKind.XLSX

    def test_a_zip_that_is_neither_is_unsupported(self) -> None:
        assert sniff(_zip({"payload.exe": b"MZ"})) is None

    def test_binary_that_matches_nothing_is_unsupported(self) -> None:
        assert sniff(b"\x00\x01\x02\x03 binary noise") is None
        assert sniff(b"MZ\x90\x00 executable") is None

    def test_csv_and_txt_differ_only_by_name(self) -> None:
        """The one thing the filename decides — and it can never promote."""
        assert sniff(b"a,b\n1,2\n", filename="p.csv") is DocumentKind.CSV
        assert sniff(b"a,b\n1,2\n", filename="p.txt") is DocumentKind.TXT

    def test_a_csv_name_cannot_make_pdf_bytes_a_csv(self) -> None:
        assert sniff(b"%PDF-1.4 x", filename="totally.csv") is DocumentKind.PDF


# --- limits, applied before parsing -----------------------------------


class TestLimits:
    def test_oversized_documents_are_refused(self) -> None:
        with pytest.raises(DocumentRejected) as raised:
            check_size(b"x" * (MAX_DOCUMENT_BYTES + 1))

        assert raised.value.reason is DocumentRejection.TOO_LARGE

    def test_a_document_at_the_limit_is_allowed(self) -> None:
        check_size(b"x" * MAX_DOCUMENT_BYTES)

    def test_an_archive_bomb_is_refused_from_its_directory(self) -> None:
        """Never unpacked. The declared sizes are enough to say no."""
        bomb = _zip({"big.xml": b"\x00" * (60 * 1024 * 1024)})

        with pytest.raises(DocumentRejected) as raised:
            check_archive_safety(bomb)

        assert raised.value.reason is DocumentRejection.ARCHIVE_BOMB

    def test_an_ordinary_office_archive_passes(self) -> None:
        check_archive_safety(_zip({"word/document.xml": b"<w:p>price</w:p>" * 100}))

    def test_a_corrupt_archive_is_refused(self) -> None:
        with pytest.raises(DocumentRejected) as raised:
            check_archive_safety(b"PK\x03\x04 truncated nonsense")

        assert raised.value.reason is DocumentRejection.CORRUPT

    def test_extracted_text_is_bounded(self) -> None:
        assert len(truncate("x" * 5_000_000)) < 5_000_000


# --- parsers ----------------------------------------------------------


class TestTextParsers:
    def test_txt_extracts(self) -> None:
        result = TxtParser().extract(b"DIA 500 Mbps is 195 JOD")

        assert "195 JOD" in result.text
        assert result.parser == "text"

    def test_csv_extracts_rows(self) -> None:
        result = CsvParser().extract(b"product,price\nDIA 500,195\n")

        assert "DIA 500" in result.text
        assert "195" in result.text

    def test_a_csv_formula_cell_is_text_and_never_evaluated(self) -> None:
        """Injection is an Excel problem. Here it is a string, and nothing in
        this path writes it back to a file something else would open."""
        result = CsvParser().extract(b"product,price\n=cmd|calc!A1,195\n")

        assert "=cmd|calc!A1" in result.text

    def test_empty_text_is_refused_rather_than_stored_as_nothing(self) -> None:
        for parser in (TxtParser(), CsvParser()):
            with pytest.raises(DocumentRejected) as raised:
                parser.extract(b"   \n  \n")
            assert raised.value.reason is DocumentRejection.EMPTY


class TestPdfParser:
    def test_a_corrupt_pdf_is_refused(self) -> None:
        with pytest.raises(DocumentRejected) as raised:
            PdfParser().extract(b"%PDF-1.4 and then garbage")

        assert raised.value.reason in {
            DocumentRejection.CORRUPT,
            DocumentRejection.NO_TEXT_LAYER,
        }

    def test_a_pdf_with_a_text_layer_extracts(self) -> None:
        pypdf = pytest.importorskip("pypdf")
        reportlab_canvas = pytest.importorskip("reportlab.pdfgen.canvas")

        buffer = io.BytesIO()
        pdf = reportlab_canvas.Canvas(buffer)
        pdf.drawString(100, 700, "DIA 500 Mbps 195 JOD")
        pdf.save()

        result = PdfParser().extract(buffer.getvalue())

        assert "195" in result.text
        assert result.parser == "pypdf"
        assert result.parser_version == pypdf.__version__ or result.parser_version

    def test_a_pdf_with_pages_and_no_text_is_refused_as_a_scan(self) -> None:
        """Half-reading a price list fails invisibly. This fails loudly."""
        reportlab_canvas = pytest.importorskip("reportlab.pdfgen.canvas")

        buffer = io.BytesIO()
        pdf = reportlab_canvas.Canvas(buffer)
        pdf.showPage()  # a page, deliberately with no text drawn on it
        pdf.save()

        with pytest.raises(DocumentRejected) as raised:
            PdfParser().extract(buffer.getvalue())

        assert raised.value.reason is DocumentRejection.NO_TEXT_LAYER

    def test_an_encrypted_pdf_fails_closed(self) -> None:
        reportlab_canvas = pytest.importorskip("reportlab.pdfgen.canvas")
        pytest.importorskip("reportlab.lib.pdfencrypt")
        from reportlab.lib import pdfencrypt

        buffer = io.BytesIO()
        pdf = reportlab_canvas.Canvas(
            buffer, encrypt=pdfencrypt.StandardEncryption("ownerpass", "userpass")
        )
        pdf.drawString(100, 700, "secret pricing")
        pdf.save()

        with pytest.raises(DocumentRejected) as raised:
            PdfParser().extract(buffer.getvalue())

        assert raised.value.reason is DocumentRejection.ENCRYPTED


class TestOfficeParsers:
    def test_xlsx_reads_cached_values(self) -> None:
        openpyxl = pytest.importorskip("openpyxl")

        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet["A1"] = "DIA 500 Mbps"
        sheet["B1"] = 195
        buffer = io.BytesIO()
        workbook.save(buffer)

        result = XlsxParser().extract(buffer.getvalue())

        assert "DIA 500 Mbps" in result.text
        assert "195" in result.text

    def test_a_formula_is_not_evaluated(self) -> None:
        """``data_only=True``: the stored value, never the expression.

        A workbook whose formulas were never calculated has no cached value,
        so the cell reads as empty rather than as something this process
        computed on a stranger's behalf.
        """
        openpyxl = pytest.importorskip("openpyxl")

        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet["A1"] = "total"
        sheet["B1"] = "=1+1"
        buffer = io.BytesIO()
        workbook.save(buffer)

        result = XlsxParser().extract(buffer.getvalue())

        assert "=1+1" not in result.text

    def test_docx_reads_paragraphs_and_tables(self) -> None:
        docx = pytest.importorskip("docx")

        document = docx.Document()
        document.add_paragraph("Q3 pricing")
        table = document.add_table(rows=1, cols=2)
        table.rows[0].cells[0].text = "DIA 500 Mbps"
        table.rows[0].cells[1].text = "195 JOD"
        buffer = io.BytesIO()
        document.save(buffer)

        result = DocxParser().extract(buffer.getvalue())

        assert "Q3 pricing" in result.text
        # Tables carry the prices in most real price lists; a paragraph-only
        # walk would silently miss every one of them.
        assert "195 JOD" in result.text

    def test_a_docx_that_is_a_bomb_is_refused_before_parsing(self) -> None:
        with pytest.raises(DocumentRejected) as raised:
            DocxParser().extract(_zip({"word/document.xml": b"\x00" * (60 * 1024 * 1024)}))

        assert raised.value.reason is DocumentRejection.ARCHIVE_BOMB


class TestRegistry:
    def test_every_supported_kind_resolves_to_a_parser(self) -> None:
        for kind in DocumentKind:
            assert resolve_parser(kind) is not None, kind

    def test_parsers_declare_the_kind_they_read(self) -> None:
        for kind in DocumentKind:
            assert resolve_parser(kind).kind is kind  # type: ignore[attr-defined]


# --- structural guarantees --------------------------------------------


class TestStructuralGuards:
    PARSER_FILES = (
        SRC / "infrastructure" / "document_extraction" / "parsers.py",
        SRC / "domain" / "brain" / "documents.py",
        SRC / "application" / "brain" / "document_extraction.py",
    )

    def test_no_network_client_anywhere_in_the_document_path(self) -> None:
        """No URL is fetched: no remote image, no linked stylesheet, nothing."""
        for path in self.PARSER_FILES:
            tree = ast.parse(path.read_text(), filename=str(path))
            imported = {
                (node.module or "") for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
            } | {
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
            }
            for needle in ("httpx", "requests", "urllib", "aiohttp", "socket"):
                assert not any(needle in module for module in imported), f"{path.name}: {needle}"

    def test_no_model_is_called_from_the_document_path(self) -> None:
        """4E is not authorized."""
        for path in self.PARSER_FILES:
            text = path.read_text()
            for needle in ("AiService", "ai_provider", "suggest_", "completion"):
                assert needle not in text, f"{path.name}: {needle}"

    def test_extraction_writes_no_knowledge_records(self) -> None:
        path = SRC / "application" / "brain" / "document_extraction.py"
        tree = ast.parse(path.read_text(), filename=str(path))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }

        assert "KnowledgeRecord" not in imported
        assert "KnowledgeProposal" not in imported

    def test_macros_are_never_enabled_and_formulas_never_evaluated(self) -> None:
        """By call site, not by substring.

        The module's own prose explains that ``keep_vba`` is deliberately not
        passed, so a text search fails on the documentation of the property it
        is checking — a mistake this suite has made before. What matters is
        the keyword arguments actually handed to ``load_workbook``.
        """
        path = SRC / "infrastructure" / "document_extraction" / "parsers.py"
        tree = ast.parse(path.read_text(), filename=str(path))

        load_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "load_workbook"
        ]
        assert load_calls, "the workbook reader moved; this guard needs updating"

        for call in load_calls:
            passed = {keyword.arg: keyword.value for keyword in call.keywords}
            assert "keep_vba" not in passed, "macro streams must not be carried through"
            data_only = passed.get("data_only")
            assert (
                isinstance(data_only, ast.Constant) and data_only.value is True
            ), "formulas must never be evaluated — read the cached value only"

    def test_ocr_is_absent(self) -> None:
        """Refusing a scan is the current behaviour; OCR registers a parser
        later rather than changing the pipeline."""
        source = (SRC / "infrastructure" / "document_extraction" / "parsers.py").read_text()

        for needle in ("pytesseract", "tesseract", "easyocr", "paddleocr"):
            assert needle not in source.lower()
