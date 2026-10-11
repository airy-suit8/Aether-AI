"""
Known defects: each test states the correct behaviour and is marked xfail(strict=True) with the
finding id from AUDIT_REPORT.md. The sprint that fixes a defect removes its mark; strict means a
fix that lands without removing the mark fails the suite, so the list stays honest.

To see the real failures:  python -m pytest tests/test_known_defects.py --runxfail
"""

import tempfile

import pytest
from langchain_core.documents import Document

import rag_engine
import rag_langchain
from filemakers import make_docx, make_pdf, make_xls, make_xlsx
from helpers import DOC_TEXT, upload_text, ask, ask_stream
from fakes import ScriptedChatModel
from langchain_core.messages import AIMessage


def known(reason):
    return pytest.mark.xfail(strict=True, reason=reason)


def load(path):
    return rag_engine.load_document(str(path), path.name)


# ── R3: hybrid search ─────────────────────────────────────────────────────────

@known("R3: search_hybrid fuses on text[:120], so different chunks that open the same way are merged")
def test_fusion_keeps_different_chunks_that_share_an_opening(monkeypatch):
    opening = "Section 4.2 Safety. " + "All maintenance staff must follow the lockout procedure. " * 2
    assert len(opening) > 120
    first = {"text": opening + "Applies to turbines.", "meta": {"chunk_id": "c1", "source": "a.txt"}, "score": 0.9}
    second = {"text": opening + "Applies to pumps.", "meta": {"chunk_id": "c2", "source": "a.txt"}, "score": 0.8}
    store = rag_engine.ChromaVectorStoreWrapper()
    monkeypatch.setattr(store, "search", lambda user_id, query, k: [first, second])
    monkeypatch.setattr(store, "search_bm25", lambda user_id, query, k: [second])
    hits = store.search_hybrid(1, "lockout procedure", k=5)
    assert sorted(h["meta"]["chunk_id"] for h in hits) == ["c1", "c2"]


def _add_chunks(user_id, texts):
    rag_engine._store.add_documents(user_id, [
        Document(page_content=t, metadata={"source": f"doc{i}.txt", "page": 1, "chunk_id": f"{user_id}-{i}"})
        for i, t in enumerate(texts)
    ])


@known("R3: BM25 finds nothing for a user with a single chunk (every term's idf is negative)")
def test_bm25_finds_the_only_chunk():
    _add_chunks(860001, ["The north gate opens at six every morning"])
    assert rag_engine._store.search_bm25(860001, "north gate", k=5)


@known("R3: BM25 finds nothing for a user with two chunks when the word is in one (idf is zero)")
def test_bm25_finds_one_of_two_chunks():
    _add_chunks(860002, ["The north gate opens at six every morning", "Lunch is served in the canteen"])
    hits = rag_engine._store.search_bm25(860002, "gate", k=5)
    assert [h["meta"]["source"] for h in hits] == ["doc0.txt"]


CORPUS = [
    "Visitors sign in at the gate.",
    "Lunch is served in the canteen at noon",
    "The car park closes at nine at night",
    "Fire drills happen on the first Monday",
]


def test_bm25_control_matches_a_plain_word():
    # Same corpus as the next test: a word without punctuation is found, so BM25 itself works here
    _add_chunks(860003, CORPUS)
    assert [h["meta"]["source"] for h in rag_engine._store.search_bm25(860003, "canteen", k=5)] == ["doc1.txt"]


@known("R3: the BM25 tokenizer is lower().split(), so 'gate' never matches 'gate.'")
def test_bm25_matches_a_word_next_to_punctuation():
    _add_chunks(860004, CORPUS)
    assert [h["meta"]["source"] for h in rag_engine._store.search_bm25(860004, "gate", k=5)] == ["doc0.txt"]


# ── R9: parsing ───────────────────────────────────────────────────────────────

@known("R9: DOCX tables are dropped; only paragraphs are read")
def test_docx_table_text_is_read(tmp_path):
    path = make_docx(tmp_path / "rates.docx", ["Rates below."], table=[["Role", "Rate"], ["Engineer", "95"]])
    text = load(path)[0].page_content
    assert "Engineer" in text and "95" in text


@known("R9: a DOCX whose only content is a table gives no text, so the upload is refused")
def test_docx_with_only_a_table_is_not_empty(tmp_path):
    path = make_docx(tmp_path / "table_only.docx", [], table=[["Asset", "Owner"], ["Turbine 7", "Orion"]])
    assert load(path)


@known("R9: DOCX headers and footers are dropped")
def test_docx_header_and_footer_are_read(tmp_path):
    path = make_docx(tmp_path / "memo.docx", ["Body text."], header="CONFIDENTIAL - Netweb", footer="Page footer note")
    text = load(path)[0].page_content
    assert "CONFIDENTIAL - Netweb" in text and "Page footer note" in text


@known("R9: only the first sheet of a workbook is read")
def test_every_sheet_of_a_workbook_is_read(tmp_path):
    path = make_xlsx(tmp_path / "book.xlsx", {"Stock": [["Part"], ["Bolt"]], "Suppliers": [["Name"], ["Acme Fasteners"]]})
    text = "\n".join(d.page_content for d in load(path))
    assert "Bolt" in text and "Acme Fasteners" in text


@known("R9: leading zeros are lost in CSV (codes are read as numbers)")
def test_csv_keeps_leading_zeros(tmp_path):
    path = tmp_path / "codes.csv"
    path.write_text("Part,Code\nBolt,007\nNut,010\n", encoding="utf-8")
    assert load(path)[0].page_content == "Part: Bolt, Code: 007\nPart: Nut, Code: 010"


@known("R9: leading zeros are lost in XLSX, even in cells stored as text")
def test_xlsx_keeps_leading_zeros(tmp_path):
    path = make_xlsx(tmp_path / "codes.xlsx", {"Codes": [["Part", "Code"], ["Bolt", "007"], ["Nut", "010"]]})
    assert load(path)[0].page_content == "Part: Bolt, Code: 007\nPart: Nut, Code: 010"


@known("R9: whole numbers become floats ('5.0') when a CSV column has a blank")
def test_csv_whole_numbers_stay_whole_with_blanks(tmp_path):
    path = tmp_path / "qty.csv"
    path.write_text("Part,Qty\nBolt,5\nNut,\n", encoding="utf-8")
    assert load(path)[0].page_content.split("\n")[0] == "Part: Bolt, Qty: 5"


@known("R9: whole numbers become floats ('5.0') when an Excel column has a blank")
@pytest.mark.parametrize("maker,name", [(make_xlsx, "qty.xlsx"), (make_xls, "qty.xls")])
def test_excel_whole_numbers_stay_whole_with_blanks(tmp_path, maker, name):
    rows = [["Part", "Qty"], ["Bolt", 5], ["Nut", None]]
    path = maker(tmp_path / name, {"Sheet": rows} if name.endswith("x") else rows)
    assert load(path)[0].page_content == "Part: Bolt, Qty: 5\nPart: Nut"


@known("R9: non-UTF-8 text is read with errors='ignore', so characters are silently dropped")
def test_non_utf8_text_is_decoded_or_refused(tmp_path):
    path = tmp_path / "latin.txt"
    path.write_bytes("Le café est fermé.".encode("cp1252"))
    try:
        docs = load(path)
    except ValueError:
        return  # refusing the file with a clear error is also correct
    assert docs[0].page_content == "Le café est fermé."


@known("R9: a corrupt PDF or DOCX returns 500 (for DOCX, with the server's temp path) instead of a 422")
@pytest.mark.parametrize("filename,content", [
    ("broken.pdf", b"%PDF-1.4\nthis is not really a pdf"),
    ("broken.docx", b"PK this is not really a zip"),
])
def test_corrupt_upload_is_a_clean_422(client, make_user, filename, content):
    _, headers = make_user("corrupt")
    r = client.post("/api/v1/upload", headers=headers, files={"file": (filename, content, "application/octet-stream")})
    assert r.status_code == 422
    assert tempfile.gettempdir() not in r.json()["detail"]


# ── Sources of a refused answer (SPRINT_PLAN.md Status; R5) ───────────────────

REFUSAL = "I could not find relevant information in the uploaded documents."


@pytest.fixture
def refusing_model(monkeypatch):
    """A model that refuses every question, although retrieval passed the threshold."""
    original = ScriptedChatModel._reply

    def reply(self, messages):
        if "Answer:" in str(messages[-1].content) and "Standalone Question:" not in str(messages[-1].content):
            return AIMessage(content=REFUSAL)
        return original(self, messages)

    monkeypatch.setattr(ScriptedChatModel, "_reply", reply)


@known("R5 / Status: a refused answer still lists every retrieved chunk as a source")
@pytest.mark.parametrize("modes", [{}, {"use_hybrid": True}, {"use_langchain": True}], ids=["default", "hybrid", "langchain"])
def test_refused_answer_lists_no_sources(client, make_user, refusing_model, modes):
    _, headers = make_user("refuse")
    upload_text(client, headers, text=DOC_TEXT)
    r = ask(client, headers, "How often is the Zephyr turbine blade inspection?", **modes)
    assert r.json()["answer"] == REFUSAL
    assert r.json()["sources"] == []


@known("R5 / Status: a refused streamed answer still lists every retrieved chunk as a source")
def test_refused_streamed_answer_lists_no_sources(client, make_user, refusing_model):
    _, headers = make_user("refuses")
    upload_text(client, headers, text=DOC_TEXT)
    _, events = ask_stream(client, headers, "How often is the Zephyr turbine blade inspection?")
    assert "".join(e["content"] for e in events if e["type"] == "token") == REFUSAL
    assert events[-1]["sources"] == []


# ── Found in Sprint 2 (not in the audit) ──────────────────────────────────────

@known("New in Sprint 2: the LangChain PDF loader keeps PyPDFLoader's 0-based page numbers (cites p. 0)")
def test_langchain_pdf_pages_are_numbered_from_one(tmp_path):
    docs = rag_langchain.load_document_langchain(str(make_pdf(tmp_path / "two.pdf", ["one", "two"])), "two.pdf")
    assert [d.metadata["page"] for d in docs] == [1, 2]
