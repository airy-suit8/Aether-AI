"""
Document parsers, as they behave today: the native parsers (loader.load_document, used by every
upload by default) and the LangChain loaders (Task 12; used when settings.document_loader is
"langchain"). Defects the audit found in these parsers are in test_known_defects.py.
"""

import pytest

from src.ingestion import loader
from filemakers import make_docx, make_pdf, make_xls, make_xlsx

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


def test_pdf_with_no_text_gives_nothing(tmp_path):
    assert load(make_pdf(tmp_path / "scan.pdf", ["", ""])) == []


# ── DOCX ──────────────────────────────────────────────────────────────────────

def test_docx_paragraphs_become_one_document(tmp_path):
    path = make_docx(tmp_path / "policy.docx", ["Remote work policy", "", "Stipend is 150 per month."])
    docs = load(path)
    assert len(docs) == 1
    assert docs[0].page_content == "Remote work policy\nStipend is 150 per month."
    assert docs[0].metadata == {"source": "policy.docx", "page": 1, "type": "docx"}


def test_docx_with_a_table_still_reads_its_paragraphs(tmp_path):
    path = make_docx(tmp_path / "rates.docx", ["Rates below."], table=[["Role", "Rate"], ["Engineer", "95"]])
    docs = load(path)
    assert docs[0].page_content.startswith("Rates below.")


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


def test_xlsx_reads_the_first_sheet(tmp_path):
    path = make_xlsx(tmp_path / "book.xlsx", {"Stock": ROWS, "Suppliers": [["Name"], ["Acme"]]})
    assert "Part: Bolt" in load(path)[0].page_content


def test_xls_rows_become_labelled_lines(tmp_path):
    path = make_xls(tmp_path / "legacy.xls", ROWS)
    docs = load(path)
    assert docs[0].page_content.split("\n") == _expected_lines()
    assert docs[0].metadata == {"source": "legacy.xls", "page": 1, "type": "xls"}


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
    path = make_docx(tmp_path / "rates.docx", ["Rates below."], table=[["Role", "Rate"], ["Engineer", "95"]])
    assert "Engineer" not in load(path)[0].page_content
    monkeypatch.setattr(loader.settings, "document_loader", "langchain")
    assert "Engineer" in load(path)[0].page_content
