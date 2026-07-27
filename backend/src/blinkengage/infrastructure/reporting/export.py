"""Generic tabular PDF/Excel rendering shared by every M23 report export
endpoint. See ``docs/architecture/reports-analytics.md``.

Deliberately generic (title + headers + rows in, bytes out) rather than
one renderer per report type — every report this milestone exports is
"a table with a title," and the report-specific shaping (which columns,
what to put in each cell) already happened in
``api.v1.endpoints.reports``/``ReportingService`` before this module ever
sees the data. Adding an 11th report type later needs no change here.

Both renderers also take an optional ``logo`` (the company's uploaded
logo, fetched via ``CompanyService.get_logo`` — see
``docs/architecture/administration.md``) rendered at the top of the
document. Callers are expected to treat a logo-fetch failure as "render
without one," never as a reason to fail the export itself.
"""

import io

from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    Flowable,
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# The company's own logo, if one is set — see CompanyService.get_logo.
# Never required: every call site treats a fetch failure (or no logo
# uploaded) as "render without one," not a reason to fail the export.
CompanyLogo = tuple[bytes, str]

_PDF_LOGO_HEIGHT = 0.4 * inch
_XLSX_LOGO_HEIGHT_PX = 40


def _pdf_logo_flowable(logo: CompanyLogo) -> Flowable:
    logo_bytes, _content_type = logo
    reader = ImageReader(io.BytesIO(logo_bytes))
    width, height = reader.getSize()
    display_width = _PDF_LOGO_HEIGHT * (width / height)
    return Image(io.BytesIO(logo_bytes), width=display_width, height=_PDF_LOGO_HEIGHT)


def render_pdf_table(
    *, title: str, headers: list[str], rows: list[list[str]], logo: CompanyLogo | None = None
) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, title=title)
    styles = getSampleStyleSheet()
    elements: list[Flowable] = []
    if logo is not None:
        elements.append(_pdf_logo_flowable(logo))
        elements.append(Spacer(1, 0.15 * inch))
    elements.append(Paragraph(title, styles["Title"]))
    elements.append(Spacer(1, 0.25 * inch))

    table_data = [headers, *rows]
    table = Table(table_data, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    elements.append(table)
    doc.build(elements)
    return buffer.getvalue()


def render_excel_table(
    *, title: str, headers: list[str], rows: list[list[str]], logo: CompanyLogo | None = None
) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = title[:31] or "Report"  # Excel sheet-name length limit

    header_row_number = 1
    if logo is not None:
        logo_bytes, _content_type = logo
        image = XLImage(io.BytesIO(logo_bytes))
        original_width, original_height = image.width, image.height
        image.height = _XLSX_LOGO_HEIGHT_PX
        image.width = int(original_width * (_XLSX_LOGO_HEIGHT_PX / original_height))
        sheet.add_image(image, "A1")
        # Blank rows reserve vertical space so the header row doesn't
        # render underneath the image — openpyxl anchors an image to a
        # cell but doesn't reflow surrounding cell content around it.
        blank_rows = 3
        for _ in range(blank_rows):
            sheet.append([])
        header_row_number = blank_rows + 1

    sheet.append(headers)
    for cell in sheet[header_row_number]:
        cell.font = Font(bold=True)

    for row in rows:
        sheet.append(row)

    for index, header in enumerate(headers, start=1):
        column_letter = get_column_letter(index)
        max_length = max([len(header)] + [len(str(row[index - 1])) for row in rows], default=10)
        sheet.column_dimensions[column_letter].width = min(max_length + 2, 60)

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
