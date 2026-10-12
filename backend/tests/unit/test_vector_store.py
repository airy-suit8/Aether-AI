"""Service -> vector store: ingest then search, with cosine similarity scores (R1)."""

import uuid

import pytest

from src.core.config import settings
from src.db.database import create_user
from src.pipeline.documents import ingest_document
from src.retrieval import retriever
from src.vectordb import vector_store
from helpers import DOC_TEXT


@pytest.fixture
def user():
    """A new user: (user id, tenant id)."""
    from src.db.database import get_tenant_id
    user_id = create_user(f"store_{uuid.uuid4().hex[:8]}", "hash")
    return user_id, get_tenant_id(user_id)


def _ingest(tmp_path, user_id, text, name="notes.txt"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return ingest_document(user_id, str(path), name)


def test_collection_uses_cosine_distance():
    config = vector_store.store.chroma._collection.configuration
    assert config["hnsw"]["space"] == "cosine"


def test_ingest_then_search_returns_the_text_with_cosine_scores(tmp_path, user):
    user_id, tenant = user
    result = _ingest(tmp_path, user_id, DOC_TEXT)
    assert result["chunks"] == 1

    hits = retriever.retriever.search(tenant, DOC_TEXT, k=3)
    assert hits[0]["text"] == DOC_TEXT
    assert hits[0]["meta"]["source"] == "notes.txt"
    # Identical text has cosine similarity 1; with L2 the score scale was distorted.
    assert abs(hits[0]["score"] - 1.0) < 1e-3

    # A short question that shares a few words is clearly relevant on the cosine scale
    # (it scored about 0.16 under the old L2 conversion, below the 0.3 threshold).
    q = retriever.retriever.search(tenant, "Zephyr turbine inspection?", k=1)[0]["score"]
    assert settings.confidence_threshold < q <= 1.0


def test_unrelated_query_scores_low_and_never_negative(tmp_path, user):
    user_id, tenant = user
    _ingest(tmp_path, user_id, DOC_TEXT)
    hits = retriever.retriever.search(tenant, "quarterly marketing budget for Paris", k=5)
    assert all(0.0 <= h["score"] < settings.confidence_threshold for h in hits)
