"""
Tenant ids (S2, Sprint 5 item 1): chunks are keyed by a random tenant id per user, not by the
integer user id, which a new database hands out again.

  - a database reset does not give the next user the previous user's documents;
  - a store made the old way (chunks keyed by user_id) is read the new way after the startup
    migration, which is safe to run twice and gives no chunk to a user without a record for it;
  - the stores default to data/, and a store at the old default path is still used.
"""

import sqlite3
import uuid
from pathlib import Path

import pytest
from langchain_core.documents import Document

from src.core import config
from src.core.config import settings
from src.db import database
from src.memory import conversation
from src.pipeline import documents
from src.retrieval.retriever import Retriever
from src.vectordb.vector_store import VectorStore
from helpers import ask, upload_text, user_id_of

QUESTION = "How often is the Zephyr turbine blade inspection?"


def _register(client, name):
    password = "securepass123"
    assert client.post("/api/v1/auth/register", json={"username": name, "password": password}).status_code == 200
    r = client.post("/api/v1/auth/login", data={"username": name, "password": password})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _use_new_database(monkeypatch, path: Path):
    """What a reset is: an empty database file, while the vector store stays where it is."""
    monkeypatch.setattr(settings, "db_path", path)
    database.init_db()


@pytest.mark.parametrize("mode", ["default", "hybrid", "langchain", "agent"])
def test_a_user_registered_after_a_database_reset_sees_none_of_the_old_data(client, monkeypatch, tmp_path, mode):
    _use_new_database(monkeypatch, tmp_path / "first.db")
    alice = _register(client, f"alice_{uuid.uuid4().hex[:6]}")
    assert upload_text(client, alice).status_code == 202
    assert ask(client, alice, QUESTION, mode=mode).json()["sources"]

    # The database is replaced and the server restarted; the vector store is the same folder
    _use_new_database(monkeypatch, tmp_path / "second.db")
    documents.migrate_chunks_to_tenants()
    conversation.memory._cache.clear()

    bob = _register(client, f"bob_{uuid.uuid4().hex[:6]}")
    assert user_id_of(bob) == user_id_of(alice)  # the reused id is what used to leak (S2)
    assert client.get("/api/v1/documents", headers=bob).json() == {"documents": [], "count": 0}
    r = ask(client, bob, QUESTION, mode=mode)
    assert r.status_code == 200
    assert r.json()["sources"] == []
    assert "90 days" not in r.json()["answer"]


# ── A store made the old way ──────────────────────────────────────────────────

OLD_SCHEMA = """
CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE conversations (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL DEFAULT 1,
    session_id TEXT NOT NULL, question TEXT NOT NULL, answer TEXT NOT NULL, confidence REAL DEFAULT 0.0,
    mode TEXT DEFAULT 'original', feedback INTEGER DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE documents (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL DEFAULT 1,
    filename TEXT NOT NULL, file_hash TEXT, pages INTEGER DEFAULT 0, chunks INTEGER DEFAULT 0,
    size_bytes INTEGER DEFAULT 0, uploaded_at TEXT NOT NULL);
INSERT INTO users VALUES (2, 'owner', 'x', '2026-10-01');
INSERT INTO documents (id, user_id, filename, uploaded_at) VALUES (1, 2, 'manual.txt', '2026-10-01');
INSERT INTO documents (id, user_id, filename, uploaded_at) VALUES (2, 2, 'old.txt', '2026-10-01');
"""

OLD_CHUNKS = {
    # chunk id: (text, metadata as the code before Sprint 5 wrote it)
    "a": ("The Zephyr blades are inspected every 90 days.", {"user_id": 2, "document_id": 1, "source": "manual.txt"}),
    "b": ("The Orion team logs each inspection.", {"user_id": 2, "source": "old.txt"}),  # before document ids
    "c": ("A file whose record is gone.", {"user_id": 2, "document_id": 9, "source": "gone.txt"}),
    "d": ("A user this database never had.", {"user_id": 3, "document_id": 1, "source": "manual.txt"}),
}


@pytest.fixture
def old_store(monkeypatch, tmp_path):
    """A database and a vector store as Sprint 4 left them, with the app pointed at both."""
    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(OLD_SCHEMA)
    conn.close()
    monkeypatch.setattr(settings, "db_path", db_path)
    monkeypatch.setattr(settings, "vector_store_dir", tmp_path / "vector_store")

    store = VectorStore()
    store.chroma.add_documents(
        [Document(page_content=text, metadata={**meta, "page": 1, "chunk_id": cid}) for cid, (text, meta) in OLD_CHUNKS.items()],
        ids=list(OLD_CHUNKS),
    )
    monkeypatch.setattr(documents, "store", store)
    return store


def _metadata(store):
    res = store.collection.get(include=["metadatas"])
    return dict(zip(res["ids"], res["metadatas"]))


def test_an_old_store_is_read_the_new_way_after_the_startup_migration(old_store):
    database.init_db()  # adds the tenant_id column and gives the existing user one
    tenant = database.get_tenant_id(2)
    search = Retriever(old_store)
    assert search.search(tenant, "Zephyr blades inspected", k=5) == []  # not yet re-keyed

    assert documents.migrate_chunks_to_tenants() == {"migrated": 2, "unclaimed": 2}

    hits = search.search(tenant, "Zephyr blades inspected Orion team", k=5)
    assert sorted(h["meta"]["chunk_id"] for h in hits) == ["a", "b"]
    metas = _metadata(old_store)
    assert metas["a"]["tenant_id"] == tenant and "user_id" not in metas["a"]
    assert metas["a"]["document_id"] == 1 and metas["a"]["source"] == "manual.txt"  # the rest is kept
    # No record accounts for these two, so they go to no one, and they are not deleted
    assert metas["c"] == {**OLD_CHUNKS["c"][1], "page": 1, "chunk_id": "c"}
    assert metas["d"] == {**OLD_CHUNKS["d"][1], "page": 1, "chunk_id": "d"}


def test_the_migration_is_safe_to_run_twice(old_store):
    database.init_db()
    database.init_db()  # the column and the tenant ids are added once
    tenant = database.get_tenant_id(2)
    documents.migrate_chunks_to_tenants()
    before = _metadata(old_store)

    assert documents.migrate_chunks_to_tenants() == {"migrated": 0, "unclaimed": 2}
    assert database.get_tenant_id(2) == tenant
    assert _metadata(old_store) == before


def test_the_migration_does_nothing_without_a_store(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "vector_store_dir", tmp_path / "none")
    fresh = VectorStore()
    monkeypatch.setattr(documents, "store", fresh)
    assert documents.migrate_chunks_to_tenants() == {"migrated": 0, "unclaimed": 0}
    assert not (tmp_path / "none").exists()  # and creates nothing


def test_every_user_gets_a_different_random_tenant_id():
    ids = [database.create_user(f"tenant_{uuid.uuid4().hex[:8]}", "hash") for _ in range(3)]
    tenants = [database.get_tenant_id(i) for i in ids]
    assert len(set(tenants)) == 3
    assert all(uuid.UUID(t).version == 4 for t in tenants)
    with pytest.raises(LookupError):
        database.get_tenant_id(10**9)


# ── Where the stores are kept ─────────────────────────────────────────────────

@pytest.fixture
def paths(monkeypatch, tmp_path):
    """Default paths in a temp folder, and no path set by the environment."""
    for name in ("AETHER_DB_PATH", "AETHER_VECTOR_STORE_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "OLD_DB_PATH", tmp_path / "backend" / "aether.db")
    monkeypatch.setattr(config, "OLD_VECTOR_STORE_DIR", tmp_path / "backend" / "vector_store")
    return tmp_path


def test_the_stores_default_to_one_data_folder(paths):
    fresh = config.Settings(_env_file=None)
    assert fresh.db_path == paths / "data" / "aether.db"
    assert fresh.vector_store_dir == paths / "data" / "vector_store"
    assert fresh.path_notes() == []


def test_stores_at_the_old_default_paths_are_still_used_with_a_note(paths):
    (paths / "backend" / "vector_store").mkdir(parents=True)
    (paths / "backend" / "aether.db").write_bytes(b"")
    fresh = config.Settings(_env_file=None)
    assert fresh.db_path == paths / "backend" / "aether.db"
    assert fresh.vector_store_dir == paths / "backend" / "vector_store"
    notes = fresh.path_notes()
    assert len(notes) == 2 and "AETHER_DB_PATH" in notes[0] and "AETHER_VECTOR_STORE_DIR" in notes[1]


def test_the_new_default_wins_once_something_is_there(paths):
    (paths / "backend").mkdir()
    (paths / "backend" / "aether.db").write_bytes(b"")
    (paths / "data").mkdir()
    (paths / "data" / "aether.db").write_bytes(b"")
    fresh = config.Settings(_env_file=None)
    assert fresh.db_path == paths / "data" / "aether.db"
    assert fresh.path_notes() == []


def test_a_path_that_is_set_is_used_as_given(paths, monkeypatch):
    (paths / "backend").mkdir()
    (paths / "backend" / "aether.db").write_bytes(b"")
    monkeypatch.setenv("AETHER_DB_PATH", str(paths / "elsewhere.db"))
    fresh = config.Settings(_env_file=None)
    assert fresh.db_path == paths / "elsewhere.db"
    assert fresh.path_notes() == []
