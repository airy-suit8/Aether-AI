"""The chunker that ingest_document uses for every upload: sizes, overlap, metadata."""

import re
import uuid

import pytest

import rag_engine
from src.retrieval import retriever
from src.vectordb import vector_store
from filemakers import make_pdf
from src.chunking import chunker
from src.core.config import settings
from src.ingestion import loader

SENTENCES = [f"Sentence number {i} describes maintenance step {i} in detail." for i in range(80)]
LONG_TEXT = " ".join(SENTENCES)  # about 4,700 characters, no newlines


@pytest.fixture
def captured(monkeypatch):
    """Capture what ingest_document hands to the vector store, without embedding it."""
    stored = []
    monkeypatch.setattr(vector_store.store, "add_documents", lambda user_id, docs: stored.extend(docs))
    return stored


def _ingest(tmp_path, text, name="long.txt"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return rag_engine.ingest_document(1, str(path), name)


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
    result = rag_engine.ingest_document(1, str(path), "two.pdf")
    assert result == {"filename": "two.pdf", "pages": 2, "chunks": 2}
    assert [(c.page_content, c.metadata["page"]) for c in captured] == [("Page one text", 1), ("Page two text", 2)]


def test_nothing_to_extract_is_a_value_error_and_stores_nothing(tmp_path, captured):
    with pytest.raises(ValueError, match="No text could be extracted"):
        _ingest(tmp_path, "   ")
    assert captured == []


def test_stored_chunks_are_tagged_with_the_user(tmp_path):
    user = 880001
    path = tmp_path / "tagged.txt"
    path.write_text(LONG_TEXT, encoding="utf-8")
    rag_engine.ingest_document(user, str(path), "tagged.txt")
    metas = vector_store.store.chroma._collection.get(where={"user_id": user}, include=["metadatas"])["metadatas"]
    assert metas and all(m["user_id"] == user and m["source"] == "tagged.txt" for m in metas)


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
    user = 880002
    path = tmp_path / "lc.txt"
    path.write_text("The Halcyon register records every blade inspection.", encoding="utf-8")
    monkeypatch.setattr(settings, "document_loader", "langchain")
    assert rag_engine.ingest_document(user, str(path), "lc.txt") == {"filename": "lc.txt", "pages": 1, "chunks": 1}
    hits = retriever.retriever.search(user, "Halcyon register", k=1)
    assert hits[0]["meta"]["source"] == "lc.txt"
    with pytest.raises(ValueError):
        empty = tmp_path / "empty.txt"
        empty.write_text("", encoding="utf-8")
        rag_engine.ingest_document(user, str(empty), "empty.txt")
