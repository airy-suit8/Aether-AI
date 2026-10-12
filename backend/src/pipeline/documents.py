"""
pipeline/documents.py — the document side: ingest an upload, list a user's documents, delete them.

Ingestion is load (ingestion/) -> chunk (chunking/) -> embed and store (vectordb/). A document
is its SQLite record plus its chunks in the vector store, tied together by the record's id,
which every chunk carries as document_id (R7).
"""

from typing import Any, Dict, List, Optional

from src.chunking.chunker import split_documents
from src.db.database import (
    clear_user_documents, delete_document_record, get_all_documents_detailed, get_document,
    save_document_record, update_document_counts,
)
from src.ingestion.loader import load_document
from src.vectordb.vector_store import store


def ingest_document(user_id: int, file_path: str, filename: str, document_id: Optional[int] = None) -> Dict[str, Any]:
    """Parse → chunk → embed → store. Returns summary stats. Chunks are tagged with document_id when one is given."""
    raw_docs = load_document(file_path, filename)
    if not raw_docs:
        raise ValueError("No text could be extracted from the document.")

    chunks = split_documents(raw_docs)
    if document_id is not None:
        for chunk in chunks:
            chunk.metadata["document_id"] = document_id
    store.add_documents(user_id, chunks)

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
    deleted = store.delete_document_chunks(user_id, document_id, document["filename"])
    delete_document_record(user_id, document_id)
    return {"filename": document["filename"], "deleted": deleted}


def clear_documents(user_id: int) -> Dict[str, Any]:
    """Delete a user's documents from ChromaDB, then SQLite. Returns the number of chunks deleted."""
    # Errors propagate: the caller reports them, and the SQLite records stay
    deleted = store.delete_user_chunks(user_id)
    # Clear from SQLite metadata only once the vectors are gone
    clear_user_documents(user_id)
    return {"status": "cleared", "deleted": deleted}
