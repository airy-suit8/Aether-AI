"""
Build small document files for parser tests, in the test run, with the pinned libraries only.
Nothing binary is committed.

make_pdf   — a text PDF written by hand (pypdf reads but cannot lay out text); one string per page
make_docx  — python-docx: paragraphs, optionally a table, a header and a footer
make_xlsx  — openpyxl: one or more named sheets of rows
make_xls   — a BIFF2 worksheet written by hand (xlrd reads it; no pinned library writes .xls)
"""

import io
import struct
from pathlib import Path

from docx import Document as DocxDocument
from openpyxl import Workbook


def _pdf_string(text: str) -> str:
    return "(" + text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ")"


def make_pdf(path: Path, pages: list[str]) -> Path:
    """Write a PDF with one page per string (an empty string gives a page with no text)."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [{}] /Count {} >>".format(
            " ".join(f"{4 + 2 * i} 0 R" for i in range(len(pages))), len(pages)).encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i, text in enumerate(pages):
        lines = " ".join(f"{_pdf_string(line)} Tj T*" for line in text.split("\n")) if text else ""
        stream = f"BT /F1 12 Tf 72 720 Td 14 TL {lines} ET".encode("latin-1")
        objects.append((
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>").encode())
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    path.write_bytes(out.getvalue())
    return path


def make_docx(path: Path, paragraphs: list[str], table: list[list[str]] | None = None,
              header: str | None = None, footer: str | None = None) -> Path:
    doc = DocxDocument()
    for text in paragraphs:
        doc.add_paragraph(text)
    if table:
        t = doc.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for c, value in enumerate(row):
                t.cell(r, c).text = value
    if header:
        doc.sections[0].header.paragraphs[0].text = header
    if footer:
        doc.sections[0].footer.paragraphs[0].text = footer
    doc.save(path)
    return path


def make_xlsx(path: Path, sheets: dict[str, list[list]]) -> Path:
    """sheets maps a sheet name to its rows; the first row is the header."""
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    wb.save(path)
    return path


def _biff_record(record_type: int, data: bytes) -> bytes:
    return struct.pack("<HH", record_type, len(data)) + data


def make_xls(path: Path, rows: list[list]) -> Path:
    """A single-sheet BIFF2 .xls: strings as LABEL cells, numbers as NUMBER cells, None as blank."""
    no_attributes = b"\x00\x00\x00"
    out = _biff_record(0x0009, struct.pack("<HH", 0x0007, 0x0010))  # BOF, worksheet
    out += _biff_record(0x0042, struct.pack("<H", 1252))           # CODEPAGE
    out += _biff_record(0x0000, struct.pack("<HHHH", 0, len(rows), 0, max(len(r) for r in rows)))  # DIMENSIONS
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            if value is None:
                continue
            if isinstance(value, str):
                text = value.encode("cp1252")
                out += _biff_record(0x0004, struct.pack("<HH", r, c) + no_attributes + bytes([len(text)]) + text)
            else:
                out += _biff_record(0x0003, struct.pack("<HH", r, c) + no_attributes + struct.pack("<d", float(value)))
    out += _biff_record(0x000A, b"")  # EOF
    path.write_bytes(out)
    return path
