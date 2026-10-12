"""Service -> vector store: ingest then search, with cosine similarity scores (R1)."""

import rag_engine
from src.vectordb import vector_store
from helpers import DOC_TEXT

USER = 990001  # a user id no HTTP test creates


def _ingest(tmp_path, user_id, text, name="notes.txt"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return rag_engine.ingest_document(user_id, str(path), name)


def test_collection_uses_cosine_distance():
    config = vector_store.store.chroma._collection.configuration
    assert config["hnsw"]["space"] == "cosine"


def test_ingest_then_search_returns_the_text_with_cosine_scores(tmp_path):
    result = _ingest(tmp_path, USER, DOC_TEXT)
    assert result["chunks"] == 1

    hits = vector_store.store.search(USER, DOC_TEXT, k=3)
    assert hits[0]["text"] == DOC_TEXT
    assert hits[0]["meta"]["source"] == "notes.txt"
    # Identical text has cosine similarity 1; with L2 the score scale was distorted.
    assert abs(hits[0]["score"] - 1.0) < 1e-3

    # A short question that shares a few words is clearly relevant on the cosine scale
    # (it scored about 0.16 under the old L2 conversion, below the 0.3 threshold).
    q = vector_store.store.search(USER, "Zephyr turbine inspection?", k=1)[0]["score"]
    assert rag_engine.CONFIDENCE_THRESHOLD < q <= 1.0


def test_unrelated_query_scores_low_and_never_negative(tmp_path):
    _ingest(tmp_path, USER + 1, DOC_TEXT)
    hits = vector_store.store.search(USER + 1, "quarterly marketing budget for Paris", k=5)
    assert all(0.0 <= h["score"] < rag_engine.CONFIDENCE_THRESHOLD for h in hits)
