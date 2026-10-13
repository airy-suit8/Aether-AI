"""python -m src.maintenance (Sprint 8, item 6): it reports the chunks no document record accounts
for and the ready records with no chunks, deletes nothing without --apply, and with it deletes
exactly what it reported. On a database and a vector store of this module's own (decision 6)."""

import pytest
from langchain_core.documents import Document

from src import maintenance
from src.core.config import settings
from src.db import database
from src.vectordb import vector_store


@pytest.fixture
def stores(tmp_path, monkeypatch):
    """An empty database and vector store in a temp folder, for one test."""
    monkeypatch.setattr(settings, "db_path", tmp_path / "maintenance.db")
    monkeypatch.setattr(settings, "vector_store_dir", tmp_path / "vector_store")
    for opened in ("_client", "_collection", "_chroma"):  # reopened at the new path on first use
        monkeypatch.setattr(vector_store.store, opened, None)
    database.init_db()
    return vector_store.store


def _user():
    user_id = database.create_user("tidy", "hash")
    return user_id, database.get_tenant_id(user_id)


def _chunk(store, tenant, source, document_id, chunk_id):
    metadata = {"source": source, "page": 1, "chunk_id": chunk_id}
    if document_id is not None:
        metadata["document_id"] = document_id
    store.add_documents(tenant, [Document(page_content=f"The text of {source}.", metadata=metadata)])


@pytest.fixture
def untidy(stores):
    """A kept document and its chunk; one orphan chunk; one empty record; and two records that
    must be left alone: one still being read and one that failed."""
    user_id, tenant = _user()
    kept = database.save_document_record(user_id, "kept.txt", pages=1, chunks=1)
    _chunk(stores, tenant, "kept.txt", kept, "kept-1")
    _chunk(stores, tenant, "gone.txt", kept + 100, "orphan-1")  # its record was deleted
    empty = database.save_document_record(user_id, "empty.txt", pages=1, chunks=3)
    reading = database.save_document_record(user_id, "reading.txt", pages=0, chunks=0, status="processing")
    failed = database.save_document_record(user_id, "failed.txt", pages=0, chunks=0, status="failed")
    return {"user_id": user_id, "kept": kept, "empty": empty, "left_alone": [reading, failed]}


def _chunk_ids(store):
    return sorted(meta["chunk_id"] for meta in store.all_chunks()[1])


def _record_ids(user_id):
    return sorted(d["id"] for d in database.get_all_documents_detailed(user_id))


def test_without_apply_it_reports_both_and_deletes_nothing(untidy, stores, capsys):
    before_chunks, before_records = _chunk_ids(stores), _record_ids(untidy["user_id"])
    assert maintenance.main([]) == 0
    out = capsys.readouterr().out

    assert "Chunks no document record accounts for: 1" in out
    assert "gone.txt" in out and "kept.txt" not in out.split("Document records")[0]
    assert "Document records with no chunks: 1" in out
    assert f"record {untidy['empty']}: empty.txt" in out
    assert "reading.txt" not in out and "failed.txt" not in out
    assert "Nothing was deleted. Run again with --apply" in out
    assert _chunk_ids(stores) == before_chunks and _record_ids(untidy["user_id"]) == before_records


def test_with_apply_it_lists_then_deletes_exactly_what_it_reported(untidy, stores, capsys):
    assert maintenance.main(["--apply"]) == 0
    out = capsys.readouterr().out
    assert out.index("gone.txt") < out.index("Deleted 1 chunk and 1 record.")  # listed first

    assert _chunk_ids(stores) == ["kept-1"]
    assert _record_ids(untidy["user_id"]) == sorted([untidy["kept"], *untidy["left_alone"]])

    assert maintenance.main(["--apply"]) == 0  # and then there is nothing left to do
    assert "Nothing to tidy." in capsys.readouterr().out


def test_chunks_stored_before_ids_or_tenants_belong_to_their_record(stores, capsys):
    user_id, tenant = _user()
    database.save_document_record(user_id, "legacy.txt", pages=1, chunks=1)
    _chunk(stores, tenant, "legacy.txt", None, "legacy-1")  # before documents had ids: by name
    early = database.save_document_record(user_id, "early.txt", pages=1, chunks=1)
    # Before tenant ids, keyed by the user's number, as the startup's migration still files them
    stores.collection.add(ids=["early-1", "stray-1"], documents=["early", "stray"],
                          embeddings=[[1.0] + [0.0] * 255, [0.0, 1.0] + [0.0] * 254],
                          metadatas=[{"source": "early.txt", "user_id": user_id, "document_id": early, "chunk_id": "early-1"},
                                     {"source": "stray.txt", "user_id": 999_999, "chunk_id": "stray-1"}])

    orphans, empty = maintenance.find()
    assert [c["id"] for c in orphans] == ["stray-1"]
    assert empty == []  # both records have their chunk


def test_it_refuses_to_run_without_a_vector_store_to_compare_with(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(settings, "db_path", tmp_path / "only.db")
    monkeypatch.setattr(settings, "vector_store_dir", tmp_path / "no_store")
    database.init_db()
    user_id = database.create_user("nostore", "hash")
    database.save_document_record(user_id, "kept.txt", pages=1, chunks=1)
    assert maintenance.main(["--apply"]) == 1
    assert "No vector store at" in capsys.readouterr().err
    assert len(database.get_all_documents_detailed(user_id)) == 1  # every record would have looked empty


def test_it_needs_a_database(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(settings, "db_path", tmp_path / "missing.db")
    assert maintenance.main([]) == 1
    assert "No database at" in capsys.readouterr().err
