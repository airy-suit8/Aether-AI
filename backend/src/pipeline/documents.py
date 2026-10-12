"""
pipeline/documents.py — the document side: ingest an upload, list a user's documents, delete them.

Ingestion is load (ingestion/) -> chunk (chunking/) -> embed and store (vectordb/). A document
is its SQLite record plus its chunks in the vector store, tied together by the record's id,
which every chunk carries as document_id (R7). The chunks are filed under the owner's tenant id
(S2); migrate_chunks_to_tenants() re-keys chunks stored before there were tenant ids.
"""

from typing import Any, Dict, List, Optional

from src.chunking.chunker import split_documents
from src.core.config import settings
from src.db.database import (
    clear_user_documents, delete_document_record, get_all_documents_detailed, get_document,
    get_document_owners, get_tenant_id, save_document_record, update_document_counts,
)
from src.ingestion.loader import DocumentError, load_document
from src.vectordb.vector_store import store


def ingest_document(user_id: int, file_path: str, filename: str, document_id: Optional[int] = None) -> Dict[str, Any]:
    """Parse → chunk → embed → store. Returns summary stats. Chunks are tagged with document_id when one is given."""
    raw_docs = load_document(file_path, filename)
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


def add_document(user_id: int, file_path: str, filename: str, size_bytes: int, file_hash: str) -> Dict[str, Any]:
    """
    Ingest an upload as a document of its own. An earlier document with the same file name is
    replaced, once the new one is safely stored. Returns the stats, the new "document_id" and
    "replaced" (bool).

    The record is written first, to have an id for the chunks; if ingestion fails it is removed
    again, so a failed upload leaves nothing behind.
    """
    earlier = [d for d in get_all_documents_detailed(user_id) if d["filename"] == filename]
    document_id = save_document_record(user_id, filename, 0, 0, size_bytes, file_hash)
    try:
        result = ingest_document(user_id, file_path, filename, document_id)
    except Exception:
        delete_document_record(user_id, document_id)
        raise
    update_document_counts(user_id, document_id, result["pages"], result["chunks"])
    for old in earlier:
        delete_document(user_id, old["id"])
    return {**result, "document_id": document_id, "replaced": bool(earlier)}


def list_documents(user_id: int) -> List[str]:
    """List distinct document filenames for a user from SQLite."""
    docs = get_all_documents_detailed(user_id)
    return sorted(list(set(d["filename"] for d in docs)))


def delete_document(user_id: int, document_id: int) -> Optional[Dict[str, Any]]:
    """Delete one of a user's documents: its chunks, then its record. None if they have no such document."""
    document = get_document(user_id, document_id)
    if document is None:
        return None
    # Errors propagate, and the record stays, so the list still matches the vector store
    deleted = store.delete_document_chunks(get_tenant_id(user_id), document_id, document["filename"])
    delete_document_record(user_id, document_id)
    return {"filename": document["filename"], "deleted": deleted}


def clear_documents(user_id: int) -> Dict[str, Any]:
    """Delete a user's documents from ChromaDB, then SQLite. Returns the number of chunks deleted."""
    # Errors propagate: the caller reports them, and the SQLite records stay
    deleted = store.delete_user_chunks(get_tenant_id(user_id))
    # Clear from SQLite metadata only once the vectors are gone
    clear_user_documents(user_id)
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
