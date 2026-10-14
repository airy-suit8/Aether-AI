"""
Changing the embedding model, as from Gemini to a model in Ollama. Vectors from two models cannot
be compared, so the store records which model made its vectors, refuses to add or search with
another (and says how to fix it), and python -m src.reembed embeds every passage again, keeping
its id, text and metadata. On a vector store and a database of this module's own; the two models
are fake embeddings of different sizes, as two real models' vectors would be.
"""

import asyncio
import logging
from collections import OrderedDict

import pytest
from langchain_core.documents import Document

from fakes import HashingEmbeddings
from src import reembed
from src.core.config import settings
from src.embeddings import embedder
from src.embeddings.embedder import ModelSetupError
from src.llm import llm_client
from src.vectordb import vector_store

LOCAL = "ollama:nomic-embed-text"
PASSAGES = [
    ("tenant-a", "The Zephyr turbine blade inspection is every 90 days.", "zephyr.txt", 1),
    ("tenant-a", "The canteen opens at eight in the morning.", "canteen.txt", 2),
    ("tenant-b", "Invoices are paid within thirty days of receipt.", "invoices.txt", 3),
]


@pytest.fixture
def store(tmp_path, monkeypatch):
    """An empty vector store and database in a temp folder, opened as a fresh server would."""
    monkeypatch.setattr(settings, "vector_store_dir", tmp_path / "vector_store")
    monkeypatch.setattr(settings, "db_path", tmp_path / "model_change.db")
    for opened in ("_client", "_collection", "_chroma"):
        monkeypatch.setattr(vector_store.store, opened, None)
    monkeypatch.setattr(vector_store.store, "_query_vectors", OrderedDict())
    return vector_store.store


def fill(store):
    for tenant, text, source, document_id in PASSAGES:
        store.add_documents(tenant, [Document(page_content=text, metadata={
            "source": source, "page": 1, "document_id": document_id, "chunk_id": f"{source}-1"})])


def switch_to_local(monkeypatch, embeddings=None):
    """Configure another embedding model and reopen the store, as a restarted server would."""
    monkeypatch.setattr(settings, "embedding_provider", "ollama")
    monkeypatch.setattr(settings, "embedding_model", "nomic-embed-text")
    monkeypatch.setattr(embedder, "get_embeddings", lambda: embeddings or HashingEmbeddings(size=64))
    reopen()


def reopen():
    store = vector_store.store
    store._client = store._collection = store._chroma = None
    store._query_vectors.clear()


def stored(store):
    res = store.collection.get(include=["documents", "metadatas", "embeddings"])
    return {i: (text, meta, len(vector)) for i, text, meta, vector in
            zip(res["ids"], res["documents"], res["metadatas"], res["embeddings"])}


# ── The record, and the refusal ───────────────────────────────────────────────

def test_a_new_store_records_the_model_that_made_its_vectors(store):
    fill(store)
    assert store.collection.metadata[vector_store.EMBEDDING_KEY] == settings.embedding_label()
    assert store.embedding_model_changed() is None


def test_a_store_from_before_the_record_was_made_by_gemini_s_default_model(store):
    # Written straight into the collection, as the stores made before this change were
    store.collection.add(ids=["old-1"], embeddings=[[0.1] * 256], documents=["An old passage."],
                         metadatas=[{"tenant_id": "tenant-a", "source": "old.txt"}])
    assert vector_store.VectorStore.collection_name == "aether_collection"  # the name it always had
    assert store.embedding_model() == vector_store.FIRST_EMBEDDING == settings.embedding_label()


def test_another_model_cannot_add_or_search_but_can_still_read_and_delete(store, monkeypatch):
    fill(store)
    switch_to_local(monkeypatch)
    for attempt in (lambda: store.similarity_search("tenant-a", "turbine inspection", k=2),
                    lambda: store.add_documents("tenant-a", [Document(page_content="New.", metadata={"source": "n.txt"})])):
        with pytest.raises(ModelSetupError) as refused:
            attempt()
        said = llm_client.setup_problem(refused.value)
        assert settings.embedding_label() in said and "python -m src.reembed --apply" in said
    # Reading and deleting embed nothing, so the library and the delete buttons keep working
    texts, _ = store.get_user_chunks("tenant-a")
    assert len(texts) == 2
    assert store.delete_document_chunks("tenant-a", 2) == 1


def test_an_empty_store_simply_takes_the_new_model(store, monkeypatch):
    assert store.embedding_model() == settings.embedding_label()  # recorded while empty
    switch_to_local(monkeypatch)
    fill(store)
    assert store.embedding_model() == LOCAL
    assert store.similarity_search("tenant-a", "turbine blade inspection", k=1)[0][0].metadata["source"] == "zephyr.txt"


def test_the_startup_log_says_when_the_model_changed(store, monkeypatch, caplog):
    from main import app, lifespan

    async def start():
        async with lifespan(app):
            pass

    fill(store)
    switch_to_local(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="aether.errors"):
        asyncio.run(start())
    assert any("python -m src.reembed --apply" in r.getMessage() for r in caplog.records)


# ── Re-embedding ──────────────────────────────────────────────────────────────

def test_reembedding_keeps_every_passage_and_makes_them_searchable_again(store, monkeypatch):
    fill(store)
    before = stored(store)
    switch_to_local(monkeypatch)
    assert store.reembed() == len(PASSAGES)

    after = stored(store)
    assert after.keys() == before.keys()
    for chunk_id, (text, meta, size) in after.items():
        assert (text, meta) == before[chunk_id][:2] and size == 64
    assert store.embedding_model() == LOCAL and store.embedding_model_changed() is None
    found = store.similarity_search("tenant-a", "turbine blade inspection", k=2)
    assert found[0][0].metadata["source"] == "zephyr.txt"
    assert {doc.metadata["tenant_id"] for doc, _ in found} == {"tenant-a"}  # still one tenant's own
    names = {getattr(c, "name", c) for c in store._client.list_collections()}
    assert names == {"aether_collection"}


class FailsOnSecondBatch(HashingEmbeddings):
    """A model that stops part-way, as Ollama does when it is closed during the run."""
    batches: int = 0

    def embed_documents(self, texts):
        FailsOnSecondBatch.batches += 1
        if FailsOnSecondBatch.batches == 2:
            raise ConnectionError("Failed to connect to Ollama. Please check that Ollama is downloaded, running and accessible.")
        return super().embed_documents(texts)


def test_a_run_that_fails_part_way_leaves_the_store_as_it_was_and_can_be_run_again(store, monkeypatch):
    fill(store)
    before = stored(store)
    monkeypatch.setattr(vector_store, "REEMBED_BATCH", 1)
    FailsOnSecondBatch.batches = 0
    switch_to_local(monkeypatch, FailsOnSecondBatch(size=64))
    with pytest.raises(ConnectionError):
        store.reembed()

    reopen()
    assert stored(store) == before
    assert store.embedding_model() == vector_store.FIRST_EMBEDDING
    # The half-made vectors are not taken for the store, and the next run replaces them
    monkeypatch.setattr(embedder, "get_embeddings", lambda: HashingEmbeddings(size=64))
    assert store.reembed() == len(PASSAGES)
    assert store.embedding_model() == LOCAL


def test_a_complete_rebuild_stopped_before_its_rename_becomes_the_store(store, monkeypatch):
    fill(store)
    before = stored(store)
    switch_to_local(monkeypatch)
    # As if the process stopped between deleting the old collection and renaming the new one
    client = store.collection and store._client
    rebuild = client.create_collection(store.rebuild_name, configuration=vector_store.COLLECTION_CONFIGURATION,
                                       metadata={vector_store.EMBEDDING_KEY: LOCAL, "complete": True})
    ids = list(before)
    rebuild.add(ids=ids, documents=[before[i][0] for i in ids], metadatas=[before[i][1] for i in ids],
                embeddings=HashingEmbeddings(size=64).embed_documents([before[i][0] for i in ids]))
    client.delete_collection(store.collection_name)

    reopen()
    assert {i: v[:2] for i, v in stored(store).items()} == {i: v[:2] for i, v in before.items()}
    assert store.collection.metadata == {vector_store.EMBEDDING_KEY: LOCAL}
    assert store.embedding_model_changed() is None


# ── python -m src.reembed ─────────────────────────────────────────────────────

def test_the_command_reports_and_changes_nothing_without_apply(store, monkeypatch, capsys):
    fill(store)
    switch_to_local(monkeypatch)
    assert reembed.main([]) == 0
    out = capsys.readouterr().out
    assert f"Stored passages: 3, embedded with {vector_store.FIRST_EMBEDDING}" in out
    assert f"Configured embedding model: {LOCAL}" in out and "Nothing was changed" in out
    assert store.embedding_model() == vector_store.FIRST_EMBEDDING


def test_the_command_reembeds_with_apply(store, monkeypatch, capsys):
    fill(store)
    switch_to_local(monkeypatch)
    assert reembed.main(["--apply"]) == 0
    assert "Done: 3 passages embedded with ollama:nomic-embed-text." in capsys.readouterr().out
    assert store.embedding_model() == LOCAL
    assert reembed.main([]) == 0
    assert "They match: nothing to do." in capsys.readouterr().out


def test_the_command_says_plainly_why_it_stopped(store, monkeypatch, capsys):
    fill(store)
    FailsOnSecondBatch.batches = 1  # the first batch already fails
    switch_to_local(monkeypatch, FailsOnSecondBatch(size=64))
    assert reembed.main(["--apply"]) == 1
    err = capsys.readouterr().err
    assert "the store is as it was" in err and llm_client.OLLAMA_NOT_RUNNING in err
    assert store.embedding_model() == vector_store.FIRST_EMBEDDING


def test_the_command_with_no_store_has_nothing_to_do(store, capsys):
    assert reembed.main(["--apply"]) == 0
    assert "there is nothing to embed" in capsys.readouterr().out
    assert not store.exists()
