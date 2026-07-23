"""Generic tabular PDF/Excel rendering shared by every M23 report export
endpoint. See ``docs/architecture/reports-analytics.md``.

Deliberately generic (title + headers + rows in, bytes out) rather than
one renderer per report type — every report this milestone exports is
"a table with a title," and the report-specific shaping (which columns,
what to put in each cell) already happened in
``api.v1.endpoints.reports``/``ReportingService`` before this module ever
sees the data. Adding an 11th report type later needs no change here.
"""

import io

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def render_pdf_table(*, title: str, headers: list[str], rows: list[list[str]]) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, title=title)
    styles = getSampleStyleSheet()
    elements = [Paragraph(title, styles["Title"]), Spacer(1, 0.25 * inch)]

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


def render_excel_table(*, title: str, headers: list[str], rows: list[list[str]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = title[:31] or "Report"  # Excel sheet-name length limit

    sheet.append(headers)
    for cell in sheet[1]:
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
