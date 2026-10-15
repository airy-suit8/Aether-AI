"""
pipeline/documents.py — the document side: ingest an upload, list a user's documents, delete them.

Ingestion is load (ingestion/) -> chunk (chunking/) -> embed and store (vectordb/). A document
is its SQLite record plus its chunks in the vector store, tied together by the record's id,
which every chunk carries as document_id (R7). The chunks are filed under the owner's tenant id
(S2); migrate_chunks_to_tenants() re-keys chunks stored before there were tenant ids.

A PDF is also kept as it was uploaded (its "original", in settings.files_dir under the owner's
tenant id), so a source can be shown on its page; it goes with its document. PDFs uploaded before
15 Oct 2026 were not kept: the same file uploaded again is kept for its document (keep_original).
"""

import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.chunking.chunker import split_documents
from src.core.config import settings
from src.db.database import (
    clear_user_documents, delete_document_record, fail_processing_documents, get_all_documents_detailed,
    get_document, get_document_owners, get_tenant_id, save_document_record, set_document_status,
)
from src.ingestion.loader import DocumentError, load_document
from src.vectordb.vector_store import store

# A document whose reading a restart cut short
INTERRUPTED = "The server stopped before this file was read. Upload it again."

# The kinds of file kept as uploaded: the page viewer shows PDFs
KEPT_KINDS = (".pdf",)


class DocumentRemoved(Exception):
    """The user removed a document while it was being read; nothing of it was kept."""


def ingest_document(user_id: int, file_path: str, filename: str, document_id: Optional[int] = None) -> Dict[str, Any]:
    """Parse → chunk → embed → store. Returns summary stats. Chunks are tagged with document_id when one is given."""
    raw_docs = load_document(file_path, filename, owner=str(user_id))  # a scan counts against their OCR limit
    if not raw_docs:
        raise ValueError("No text could be extracted from the document.")

    chunks = split_documents(raw_docs)
    if len(chunks) > settings.max_chunks_per_document:  # S4: each chunk is an embedding call's worth of work
        raise DocumentError(
            f"'{filename}' is too long: it makes {len(chunks):,} passages, and one file may make "
            f"{settings.max_chunks_per_document:,}. Split it into smaller files and upload those.")
    if document_id is not None:
        for chunk in chunks:
            chunk.metadata["document_id"] = document_id
    store.add_documents(get_tenant_id(user_id), chunks)

    return {"filename": filename, "pages": len(raw_docs), "chunks": len(chunks)}


def accept_document(user_id: int, filename: str, size_bytes: int, file_hash: str) -> Dict[str, Any]:
    """
    Record an upload as "processing", before it is read. Returns its "document_id", and
    "replaces": whether a document of the same name exists (it is replaced once this one is read).
    finish_document() then reads it, in the background (R12).
    """
    replaces = any(d["filename"] == filename for d in get_all_documents_detailed(user_id))
    document_id = save_document_record(user_id, filename, 0, 0, size_bytes, file_hash, status="processing")
    return {"document_id": document_id, "replaces": replaces}


def finish_document(user_id: int, document_id: int, file_path: str, filename: str) -> Dict[str, Any]:
    """
    Read an accepted upload into the vector store and mark it "ready"; then remove any other
    document of the same name, which it replaces. Returns the stats and "replaced" (bool).
    Errors propagate: the caller reports them with fail_document(), and an earlier file of the
    same name is kept. DocumentRemoved when the user removed the document while it was read: its
    passages, stored by then, are removed again, so none stays searchable without a record (N2).
    """
    result = ingest_document(user_id, file_path, filename, document_id)
    if not set_document_status(user_id, document_id, "ready", pages=result["pages"], chunks=result["chunks"]):
        store.delete_document_chunks(get_tenant_id(user_id), document_id)
        raise DocumentRemoved(filename)
    earlier = [d for d in get_all_documents_detailed(user_id) if d["filename"] == filename and d["id"] != document_id]
    for old in earlier:
        delete_document(user_id, old["id"])
    return {**result, "replaced": bool(earlier)}


def original_path(user_id: int, document_id: int) -> Path:
    """Where a document's original file is kept: under its owner's tenant id, by the document's id."""
    return settings.files_dir / get_tenant_id(user_id) / f"{document_id}.pdf"


def has_original(user_id: int, document_id: int) -> bool:
    return original_path(user_id, document_id).is_file()


def keep_original(user_id: int, document_id: int, file_path: str, filename: str) -> bool:
    """Keep an uploaded file of a kind the viewer shows as its document's original, moving it from
    file_path. Returns whether it was kept."""
    if Path(filename).suffix.lower() not in KEPT_KINDS:
        return False
    target = original_path(user_id, document_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(file_path, target)
    return True


def fail_document(user_id: int, document_id: int, error: str) -> None:
    """Mark an upload "failed" with a message for its owner, then remove any chunks it got as far as storing."""
    set_document_status(user_id, document_id, "failed", error=error)
    store.delete_document_chunks(get_tenant_id(user_id), document_id)


def recover_interrupted_uploads() -> int:
    """
    At startup: a document still "processing" was being read when the server stopped. Mark it
    failed, so its owner sees what happened, and remove any chunks it had stored. Returns how
    many there were.
    """
    interrupted = fail_processing_documents(INTERRUPTED)
    if interrupted and store.exists():
        for doc in interrupted:
            store.delete_document_chunks(get_tenant_id(doc["user_id"]), doc["document_id"])
    return len(interrupted)


def list_documents(user_id: int) -> List[str]:
    """The distinct names of a user's documents that are ready to be searched."""
    docs = get_all_documents_detailed(user_id)
    return sorted({d["filename"] for d in docs if d["status"] == "ready"})


def delete_document(user_id: int, document_id: int) -> Optional[Dict[str, Any]]:
    """Delete one of a user's documents: its chunks, then its record. None if they have no such document."""
    document = get_document(user_id, document_id)
    if document is None:
        return None
    # Errors propagate, and the record stays, so the list still matches the vector store
    deleted = store.delete_document_chunks(get_tenant_id(user_id), document_id, document["filename"])
    delete_document_record(user_id, document_id)
    original_path(user_id, document_id).unlink(missing_ok=True)
    return {"filename": document["filename"], "deleted": deleted}


def clear_documents(user_id: int) -> Dict[str, Any]:
    """Delete a user's documents from ChromaDB, then SQLite. Returns the number of chunks deleted."""
    # Errors propagate: the caller reports them, and the SQLite records stay
    deleted = store.delete_user_chunks(get_tenant_id(user_id))
    # Clear from SQLite metadata only once the vectors are gone
    clear_user_documents(user_id)
    shutil.rmtree(settings.files_dir / get_tenant_id(user_id), ignore_errors=True)
    return {"status": "cleared", "deleted": deleted}


def migrate_chunks_to_tenants() -> Dict[str, int]:
    """
    File the chunks stored before Sprint 5, which carry the owner's integer user_id, under that
    user's tenant id (S2). Runs at startup; safe to run again, since a re-keyed chunk has no
    user_id left. Returns how many chunks were re-keyed and how many were left unclaimed.

    A chunk goes to a user only when that user has a document record for it: the same
    document_id and file name or, for a chunk stored before documents had ids, the same file
    name. A chunk no record accounts for, left behind when the database was reset, goes to no
    one, so a new user who is given a reused id does not see it. Nothing is deleted.
    """
    if not store.exists():
        return {"migrated": 0, "unclaimed": 0}
    ids, metas = store.chunks_without_tenant()
    if not ids:
        return {"migrated": 0, "unclaimed": 0}

    by_record, by_name = {}, {}
    for owner in get_document_owners():
        by_record[(owner["user_id"], owner["document_id"], owner["filename"])] = owner["tenant_id"]
        by_name[(owner["user_id"], owner["filename"])] = owner["tenant_id"]

    tenants = {}
    for chunk_id, meta in zip(ids, metas):
        if "document_id" in meta:
            tenant = by_record.get((meta["user_id"], meta["document_id"], meta.get("source")))
        else:
            tenant = by_name.get((meta["user_id"], meta.get("source")))
        if tenant:
            tenants[chunk_id] = tenant
    store.set_tenants(tenants)
    return {"migrated": len(tenants), "unclaimed": len(ids) - len(tenants)}
