"""
Document parsers: the native parsers (loader.load_document, used by every upload by default)
and the LangChain loaders (Task 12; used when settings.document_loader is "langchain").
Tests marked R9 were known defects until Sprint 4.
"""

import json
import tempfile
from datetime import datetime

import pytest
from docx import Document as DocxDocument

from src.core.config import settings
from src.core.logging import error_logger
from src.ingestion import loader
from src.ingestion.loader import DocumentError
from filemakers import make_docx, make_pdf, make_xls, make_xlsx
from helpers import status_of

ROWS = [["Part", "Qty", "Bin"], ["Bolt", 5, "A1"], ["Nut", 12, "B2"], ["Washer", 30, "C3"]]


def load(path):
    return loader.load_document(str(path), path.name)


# ── PDF ───────────────────────────────────────────────────────────────────────

def test_pdf_one_document_per_page_with_text(tmp_path):
    path = make_pdf(tmp_path / "manual.pdf", ["Turbine overview (rev 2)", "", "Blade inspection\nevery 90 days"])
    docs = load(path)
    # The blank second page is skipped; the others keep their real page numbers
    assert [d.metadata["page"] for d in docs] == [1, 3]
    assert docs[0].page_content == "Turbine overview (rev 2)"
    assert docs[1].page_content == "Blade inspection\nevery 90 days"
    assert all(d.metadata["source"] == "manual.pdf" and d.metadata["type"] == "pdf" for d in docs)


def test_a_pdf_with_no_text_layer_says_it_looks_like_a_scan(tmp_path):
    # R9: a scanned PDF used to get "No text could be extracted", with no hint why
    with pytest.raises(DocumentError, match="'scan.pdf' has no text to read: its pages look like scans"):
        load(make_pdf(tmp_path / "scan.pdf", ["", ""]))


# ── DOCX ──────────────────────────────────────────────────────────────────────

def test_docx_paragraphs_become_one_document(tmp_path):
    path = make_docx(tmp_path / "policy.docx", ["Remote work policy", "", "Stipend is 150 per month."])
    docs = load(path)
    assert len(docs) == 1
    assert docs[0].page_content == "Remote work policy\nStipend is 150 per month."
    assert docs[0].metadata == {"source": "policy.docx", "page": 1, "type": "docx"}


def test_docx_tables_are_read_in_their_place(tmp_path):
    # R9: tables were dropped; only paragraphs were read
    doc = DocxDocument()
    doc.add_paragraph("Rates below.")
    table = doc.add_table(rows=2, cols=2)
    for r, row in enumerate([["Role", "Rate"], ["Engineer", "95"]]):
        for c, value in enumerate(row):
            table.cell(r, c).text = value
    doc.add_paragraph("Rates are reviewed in April.")
    doc.save(tmp_path / "rates.docx")
    assert load(tmp_path / "rates.docx")[0].page_content == (
        "Rates below.\nRole | Rate\nEngineer | 95\nRates are reviewed in April.")


def test_a_merged_table_cell_is_read_once(tmp_path):
    doc = DocxDocument()
    table = doc.add_table(rows=2, cols=3)
    table.cell(0, 0).merge(table.cell(0, 2)).text = "Quarterly targets"
    for c, value in enumerate(["North", "South", "East"]):
        table.cell(1, c).text = value
    doc.save(tmp_path / "merged.docx")
    assert load(tmp_path / "merged.docx")[0].page_content == "Quarterly targets\nNorth | South | East"


def test_docx_with_only_a_table_is_not_empty(tmp_path):
    # R9: such a file gave no text, so the upload was refused
    path = make_docx(tmp_path / "table_only.docx", [], table=[["Asset", "Owner"], ["Turbine 7", "Orion"]])
    assert load(path)[0].page_content == "Asset | Owner\nTurbine 7 | Orion"


def test_docx_header_and_footer_are_read(tmp_path):
    # R9: headers and footers were dropped
    path = make_docx(tmp_path / "memo.docx", ["Body text."], header="CONFIDENTIAL - Netweb", footer="Page footer note")
    assert load(path)[0].page_content == "CONFIDENTIAL - Netweb\nBody text.\nPage footer note"


def test_empty_docx_gives_nothing(tmp_path):
    assert load(make_docx(tmp_path / "empty.docx", [])) == []


# ── Text and Markdown ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["notes.txt", "README.md", "guide.markdown", "SHOUTING.TXT"])
def test_text_and_markdown_are_read_whole(tmp_path, name):
    text = "# Heading\n\nNaïve café, **bold** and `code`.\n"
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    docs = load(path)
    assert len(docs) == 1
    assert docs[0].page_content == text.strip()
    assert docs[0].metadata == {"source": name, "page": 1, "type": "text"}


def test_whitespace_only_text_gives_nothing(tmp_path):
    path = tmp_path / "blank.txt"
    path.write_text(" \n\t\n", encoding="utf-8")
    assert load(path) == []


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "utf-16-le-with-bom"])
def test_text_with_a_byte_order_mark_is_decoded(tmp_path, encoding):
    text = "Le café est fermé."
    data = b"\xff\xfe" + text.encode("utf-16-le") if encoding == "utf-16-le-with-bom" else text.encode(encoding)
    path = tmp_path / "bom.txt"
    path.write_bytes(data)
    assert load(path)[0].page_content == text  # and the mark itself is not part of the text


@pytest.mark.parametrize("name,data", [
    ("latin.txt", "Le café est fermé.".encode("cp1252")),
    ("latin.csv", "Nom,Lieu\nAndré,Café\n".encode("cp1252")),
])
def test_text_that_is_not_utf8_is_refused_not_guessed(tmp_path, name, data):
    # R9: such a file was read with errors="ignore", so characters were silently dropped
    path = tmp_path / name
    path.write_bytes(data)
    with pytest.raises(DocumentError, match=f"'{name}' is not saved as UTF-8 text"):
        load(path)


def test_unsupported_extension_is_a_value_error(tmp_path):
    path = tmp_path / "slides.pptx"
    path.write_bytes(b"PK")
    with pytest.raises(ValueError, match="Unsupported file type '.pptx'"):
        load(path)


# ── CSV, XLSX, XLS ────────────────────────────────────────────────────────────

def _expected_lines():
    return ["Part: Bolt, Qty: 5, Bin: A1", "Part: Nut, Qty: 12, Bin: B2", "Part: Washer, Qty: 30, Bin: C3"]


def test_csv_rows_become_labelled_lines(tmp_path):
    path = tmp_path / "parts.csv"
    path.write_text("\n".join(",".join(str(v) for v in row) for row in ROWS) + "\n", encoding="utf-8")
    docs = load(path)
    assert len(docs) == 1
    assert docs[0].page_content.split("\n") == _expected_lines()
    assert docs[0].metadata == {"source": "parts.csv", "page": 1, "type": "csv"}


def test_csv_blank_cells_are_left_out_of_the_line(tmp_path):
    path = tmp_path / "gaps.csv"
    path.write_text("Name,Team,Room\nAsha,,12\n", encoding="utf-8")
    assert load(path)[0].page_content == "Name: Asha, Room: 12"


def test_csv_rows_are_grouped_fifty_per_document(tmp_path):
    path = tmp_path / "many.csv"
    path.write_text("Id,Value\n" + "".join(f"{i},v{i}\n" for i in range(120)), encoding="utf-8")
    docs = load(path)
    assert [len(d.page_content.split("\n")) for d in docs] == [50, 50, 20]
    assert [d.metadata["page"] for d in docs] == [1, 2, 3]
    assert docs[2].page_content.split("\n")[-1] == "Id: 119, Value: v119"


def test_csv_with_only_a_header_gives_nothing(tmp_path):
    path = tmp_path / "header.csv"
    path.write_text("A,B\n", encoding="utf-8")
    assert load(path) == []


def test_xlsx_rows_become_labelled_lines(tmp_path):
    path = make_xlsx(tmp_path / "parts.xlsx", {"Stock": ROWS})
    docs = load(path)
    assert docs[0].page_content.split("\n") == _expected_lines()
    assert docs[0].metadata == {"source": "parts.xlsx", "page": 1, "type": "xlsx"}


def test_every_sheet_of_a_workbook_is_read_under_its_name(tmp_path):
    # R9: only the first sheet was read
    path = make_xlsx(tmp_path / "book.xlsx", {"Stock": ROWS, "Empty": [["A"]], "Suppliers": [["Name"], ["Acme Fasteners"]]})
    docs = load(path)
    assert [d.page_content.split("\n")[0] for d in docs] == ["Sheet: Stock", "Sheet: Suppliers"]
    assert docs[0].page_content.split("\n")[1:] == _expected_lines()
    assert docs[1].page_content == "Sheet: Suppliers\nName: Acme Fasteners"
    assert [d.metadata["page"] for d in docs] == [1, 2]


def test_xls_rows_become_labelled_lines(tmp_path):
    path = make_xls(tmp_path / "legacy.xls", ROWS)
    docs = load(path)
    assert docs[0].page_content.split("\n") == _expected_lines()
    assert docs[0].metadata == {"source": "legacy.xls", "page": 1, "type": "xls"}


def test_csv_keeps_values_as_typed(tmp_path):
    # R9: codes lost their leading zeros, and 5 became 5.0 when the column had a blank
    path = tmp_path / "codes.csv"
    path.write_text("Part,Code,Qty,Note\nBolt,007,5,NA\nNut,010,,1e3\n", encoding="utf-8")
    assert load(path)[0].page_content == "Part: Bolt, Code: 007, Qty: 5, Note: NA\nPart: Nut, Code: 010, Note: 1e3"


def test_xlsx_keeps_leading_zeros(tmp_path):
    # R9: lost even in cells stored as text
    path = make_xlsx(tmp_path / "codes.xlsx", {"Codes": [["Part", "Code"], ["Bolt", "007"], ["Nut", "010"]]})
    assert load(path)[0].page_content == "Part: Bolt, Code: 007\nPart: Nut, Code: 010"


@pytest.mark.parametrize("maker,name", [(make_xlsx, "qty.xlsx"), (make_xls, "qty.xls")])
def test_excel_whole_numbers_stay_whole_with_blanks(tmp_path, maker, name):
    # R9: 5 became 5.0 when the column had a blank
    rows = [["Part", "Qty"], ["Bolt", 5], ["Nut", None]]
    path = maker(tmp_path / name, {"Sheet": rows} if name.endswith("x") else rows)
    assert load(path)[0].page_content == "Part: Bolt, Qty: 5\nPart: Nut"


def test_excel_dates_and_decimals_read_as_a_person_would_write_them(tmp_path):
    rows = [["Item", "Due", "Logged", "Rate"],
            ["Audit", datetime(2026, 3, 5), datetime(2026, 3, 5, 14, 30), 2.5]]
    path = make_xlsx(tmp_path / "plan.xlsx", {"Plan": rows})
    assert load(path)[0].page_content == "Item: Audit, Due: 2026-03-05, Logged: 2026-03-05 14:30:00, Rate: 2.5"


# ── Files that cannot be read (R9) ────────────────────────────────────────────

@pytest.mark.parametrize("filename,content", [
    ("broken.pdf", b"%PDF-1.4\nthis is not really a pdf"),
    ("broken.docx", b"PK this is not really a zip"),
    ("broken.xlsx", b"PK this is not really a zip"),
    ("broken.xls", b"this is not really a workbook"),
])
def test_corrupt_upload_fails_with_a_clean_message(client, make_user, filename, content):
    # R9: these returned 500, and for DOCX the message quoted the server's temp path. The file is
    # read in the background since Sprint 5 (R12), so the message is in its status.
    _, headers = make_user("corrupt")
    r = client.post("/api/v1/upload", headers=headers, files={"file": (filename, content, "application/octet-stream")})
    document = status_of(client, headers, r)
    kind = filename.rsplit(".", 1)[1]
    assert document["status"] == "failed"
    assert document["error"] == (
        f"'{filename}' could not be read. It may be damaged, password-protected, or not really a {kind} file.")
    assert tempfile.gettempdir() not in str(document)
    assert client.get("/api/v1/documents", headers=headers).json()["count"] == 0

    # The parser's own error is not lost: it is in the error log, for whoever runs the server
    for handler in error_logger.handlers:
        handler.flush()
    lines = [json.loads(line) for line in (settings.log_dir / "errors.log").read_text(encoding="utf-8").splitlines()]
    logged = [line for line in lines if line["event"] == "upload_unreadable" and line["file"] == filename]
    assert logged and logged[-1]["cause"] != "None"


def test_a_scanned_pdf_upload_fails_and_says_so(client, make_user, tmp_path):
    _, headers = make_user("scan")
    data = make_pdf(tmp_path / "scan.pdf", [""]).read_bytes()
    r = client.post("/api/v1/upload", headers=headers, files={"file": ("scan.pdf", data, "application/pdf")})
    document = status_of(client, headers, r)
    assert document["status"] == "failed" and "look like scans or photos" in document["error"]


# ── LangChain loaders (Task 12) ───────────────────────────────────────────────

def lc_load(path):
    return loader.load_document_langchain(str(path), path.name)


def test_langchain_pdf_loader_reads_each_page(tmp_path):
    docs = lc_load(make_pdf(tmp_path / "manual.pdf", ["First page text", "Second page text"]))
    assert [d.page_content.strip() for d in docs] == ["First page text", "Second page text"]
    assert all(d.metadata["source"] == "manual.pdf" and d.metadata["type"] == "pdf" for d in docs)


def test_langchain_pdf_pages_are_numbered_from_one(tmp_path):
    # Was a known defect (Sprint 2): PyPDFLoader's 0-based pages would have been cited as "p. 0"
    docs = lc_load(make_pdf(tmp_path / "two.pdf", ["one", "two"]))
    assert [d.metadata["page"] for d in docs] == [1, 2]


def test_langchain_docx_loader_includes_tables(tmp_path):
    path = make_docx(tmp_path / "rates.docx", ["Rates below."], table=[["Role", "Rate"], ["Engineer", "95"]])
    docs = lc_load(path)
    assert len(docs) == 1
    assert "Rates below." in docs[0].page_content and "Engineer" in docs[0].page_content
    assert docs[0].metadata["page"] == 1 and docs[0].metadata["type"] == "docx"


def test_langchain_text_loader(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("# Notes\nNaïve café", encoding="utf-8")
    docs = lc_load(path)
    assert docs[0].page_content == "# Notes\nNaïve café"
    assert docs[0].metadata["source"] == "notes.md" and docs[0].metadata["page"] == 1


def test_langchain_text_loader_rejects_non_utf8(tmp_path):
    path = tmp_path / "latin.txt"
    path.write_bytes("café".encode("cp1252"))
    with pytest.raises(RuntimeError):
        lc_load(path)


def test_langchain_csv_loader_gives_one_document_per_row(tmp_path):
    path = tmp_path / "parts.csv"
    path.write_text("Part,Bin\nBolt,007\nNut,010\n", encoding="utf-8")
    docs = lc_load(path)
    assert [d.page_content for d in docs] == ["Part: Bolt\nBin: 007", "Part: Nut\nBin: 010"]
    assert all(d.metadata["source"] == "parts.csv" and d.metadata["type"] == "csv" for d in docs)


@pytest.mark.parametrize("maker,name", [(make_xlsx, "parts.xlsx"), (make_xls, "parts.xls")])
def test_langchain_excel_rows_become_labelled_lines(tmp_path, maker, name):
    path = maker(tmp_path / name, {"Stock": ROWS} if name.endswith("x") else ROWS)
    docs = lc_load(path)
    assert docs[0].page_content.count("\n") == 2 and "Part: Nut" in docs[0].page_content
    assert docs[0].metadata == {"source": name, "page": 1, "type": name.rsplit(".", 1)[1]}


def test_langchain_empty_workbook_gives_nothing(tmp_path):
    assert lc_load(make_xlsx(tmp_path / "empty.xlsx", {"Sheet": [["A", "B"]]})) == []


def test_langchain_unsupported_extension_is_a_value_error(tmp_path):
    path = tmp_path / "a.pptx"
    path.write_bytes(b"PK")
    with pytest.raises(ValueError):
        lc_load(path)


def test_the_setting_chooses_the_loader(tmp_path, monkeypatch):
    path = tmp_path / "parts.csv"
    path.write_text("Part,Bin\nBolt,007\nNut,010\n", encoding="utf-8")
    assert [d.page_content for d in load(path)] == ["Part: Bolt, Bin: 007\nPart: Nut, Bin: 010"]  # native: rows grouped
    monkeypatch.setattr(loader.settings, "document_loader", "langchain")
    assert len(load(path)) == 2                                                                   # CSVLoader: one per row


def test_a_langchain_loader_error_is_also_a_clean_document_error(tmp_path, monkeypatch):
    monkeypatch.setattr(loader.settings, "document_loader", "langchain")
    path = tmp_path / "latin.txt"
    path.write_bytes("café".encode("cp1252"))
    with pytest.raises(DocumentError, match="'latin.txt' could not be read") as caught:
        load(path)
    assert caught.value.__cause__ is not None and str(tmp_path) not in str(caught.value)
