"""The chunker that ingest_document uses for every upload: sizes, overlap, metadata."""

import re
import uuid

import pytest

from src.retrieval import retriever
from src.vectordb import vector_store
from filemakers import make_pdf
from src.chunking import chunker
from src.core.config import settings
from src.db import database
from src.ingestion import loader
from src.pipeline.documents import ingest_document

SENTENCES = [f"Sentence number {i} describes maintenance step {i} in detail." for i in range(80)]
LONG_TEXT = " ".join(SENTENCES)  # about 4,700 characters, no newlines


@pytest.fixture
def captured(monkeypatch):
    """Capture what ingest_document hands to the vector store, without embedding it."""
    stored = []
    monkeypatch.setattr(vector_store.store, "add_documents", lambda tenant, docs: stored.extend(docs))
    return stored


def _ingest(tmp_path, text, name="long.txt"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return ingest_document(1, str(path), name)


def test_short_text_is_one_chunk(tmp_path, captured):
    result = _ingest(tmp_path, "One short paragraph.")
    assert result == {"filename": "long.txt", "pages": 1, "chunks": 1}
    assert [c.page_content for c in captured] == ["One short paragraph."]


def test_long_text_is_split_within_the_size_limit_and_loses_nothing(tmp_path, captured):
    result = _ingest(tmp_path, LONG_TEXT)
    assert result["chunks"] == len(captured) > 4
    assert all(len(c.page_content) <= settings.chunk_size for c in captured)
    joined = " ".join(c.page_content for c in captured)
    assert all(s.rstrip(".") in joined for s in SENTENCES)


def test_consecutive_chunks_overlap_by_at_most_the_overlap_setting(tmp_path, captured):
    _ingest(tmp_path, LONG_TEXT)
    for before, after in zip(captured, captured[1:]):
        first_number = int(re.search(r"Sentence number (\d+)", after.page_content).group(1))
        shared = f"Sentence number {first_number} "
        assert shared in before.page_content, "no overlap between consecutive chunks"
        overlap = before.page_content[before.page_content.index(shared):]
        assert len(overlap) <= settings.chunk_overlap


def test_chunks_keep_source_page_and_type_and_get_unique_ids(tmp_path, captured):
    _ingest(tmp_path, LONG_TEXT, name="manual.md")
    ids = [c.metadata["chunk_id"] for c in captured]
    assert len(set(ids)) == len(ids)
    assert all(uuid.UUID(i) for i in ids)
    assert all(c.metadata["source"] == "manual.md" and c.metadata["page"] == 1 and c.metadata["type"] == "text"
               for c in captured)


def test_chunks_keep_their_pdf_page(tmp_path, captured):
    path = make_pdf(tmp_path / "two.pdf", ["Page one text", "Page two text"])
    result = ingest_document(1, str(path), "two.pdf")
    assert result == {"filename": "two.pdf", "pages": 2, "chunks": 2}
    assert [(c.page_content, c.metadata["page"]) for c in captured] == [("Page one text", 1), ("Page two text", 2)]


def test_a_row_wider_than_a_chunk_is_cut_between_fields_never_inside_one(tmp_path, captured):
    # R9: a wide row was cut wherever the size ran out, in the middle of a value
    fields = [(f"Col{i:02d}", f"value-{i:02d}-" + "x" * 20) for i in range(60)]  # one row of about 2,300 characters
    path = tmp_path / "wide.csv"
    path.write_text(",".join(name for name, _ in fields) + "\n" + ",".join(value for _, value in fields) + "\n", encoding="utf-8")
    result = ingest_document(1, str(path), "wide.csv")
    assert result["chunks"] == len(captured) > 2
    whole_fields = re.compile(r"Col\d\d: value-\d\d-x{20}(, Col\d\d: value-\d\d-x{20})*")
    assert all(whole_fields.fullmatch(c.page_content) and len(c.page_content) <= settings.chunk_size for c in captured)
    joined = " ".join(c.page_content for c in captured)
    assert all(f"{name}: {value}" in joined for name, value in fields)


def test_rows_that_fit_are_kept_whole(tmp_path, captured):
    path = tmp_path / "rows.csv"
    path.write_text("Id,Note\n" + "".join(f"{i},{'note ' * 12}{i}\n" for i in range(60)), encoding="utf-8")
    ingest_document(1, str(path), "rows.csv")
    assert len(captured) > 3
    assert all(re.fullmatch(r"Id: \d+, Note: (note ){12}\d+", line) for c in captured for line in c.page_content.split("\n"))


def test_nothing_to_extract_is_a_value_error_and_stores_nothing(tmp_path, captured):
    with pytest.raises(ValueError, match="No text could be extracted"):
        _ingest(tmp_path, "   ")
    assert captured == []


def test_stored_chunks_are_tagged_with_the_user_s_tenant_id(tmp_path):
    user = database.create_user(f"tagged_{uuid.uuid4().hex[:8]}", "hash")
    tenant = database.get_tenant_id(user)
    path = tmp_path / "tagged.txt"
    path.write_text(LONG_TEXT, encoding="utf-8")
    ingest_document(user, str(path), "tagged.txt")
    metas = vector_store.store.collection.get(where={"tenant_id": tenant}, include=["metadatas"])["metadatas"]
    # The integer user id is not stored: ids restart in a new database (S2)
    assert metas and all(m["tenant_id"] == tenant and "user_id" not in m and m["source"] == "tagged.txt" for m in metas)


# ── LangChain loaders and the shared splitter (Tasks 12, 13) ──────────────────

def test_langchain_splitter_numbers_its_chunks(tmp_path):
    path = tmp_path / "long.txt"
    path.write_text(LONG_TEXT, encoding="utf-8")
    chunks = chunker.split_documents(loader.load_document_langchain(str(path), "long.txt"))
    assert len(chunks) > 4
    assert [c.metadata["chunk_index"] for c in chunks] == list(range(1, len(chunks) + 1))
    assert {c.metadata["total_chunks"] for c in chunks} == {len(chunks)}
    assert all(len(c.page_content) <= settings.chunk_size for c in chunks)


def test_langchain_ingest_stores_searchable_chunks(tmp_path, monkeypatch):
    user = database.create_user(f"lc_{uuid.uuid4().hex[:8]}", "hash")
    path = tmp_path / "lc.txt"
    path.write_text("The Halcyon register records every blade inspection.", encoding="utf-8")
    monkeypatch.setattr(settings, "document_loader", "langchain")
    assert ingest_document(user, str(path), "lc.txt") == {"filename": "lc.txt", "pages": 1, "chunks": 1}
    hits = retriever.retriever.search(database.get_tenant_id(user), "Halcyon register", k=1)
    assert hits[0]["meta"]["source"] == "lc.txt"
    with pytest.raises(ValueError):
        empty = tmp_path / "empty.txt"
        empty.write_text("", encoding="utf-8")
        ingest_document(user, str(empty), "empty.txt")
