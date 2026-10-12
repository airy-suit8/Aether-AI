"""
pipeline/documents.py — the document side: ingest an upload, list a user's documents, delete them.

Ingestion is load (ingestion/) -> chunk (chunking/) -> embed and store (vectordb/). The SQLite
record of an upload is written by the upload route once ingestion succeeds.
"""

from typing import Any, Dict, List

from src.chunking.chunker import split_documents
from src.db.database import clear_user_documents, get_all_documents_detailed
from src.ingestion.loader import load_document
from src.vectordb.vector_store import store


def ingest_document(user_id: int, file_path: str, filename: str) -> Dict[str, Any]:
    """Parse → chunk → embed → store. Returns summary stats."""
    raw_docs = load_document(file_path, filename)
    if not raw_docs:
        raise ValueError("No text could be extracted from the document.")

    chunks = split_documents(raw_docs)
    store.add_documents(user_id, chunks)

    return {"filename": filename, "pages": len(raw_docs), "chunks": len(chunks)}


def list_documents(user_id: int) -> List[str]:
    """List distinct document filenames for a user from SQLite."""
    docs = get_all_documents_detailed(user_id)
    return sorted(list(set(d["filename"] for d in docs)))


def clear_documents(user_id: int) -> Dict[str, Any]:
    """Delete a user's documents from ChromaDB, then SQLite. Returns the number of chunks deleted."""
    # Errors propagate: the caller reports them, and the SQLite records stay
    deleted = store.delete_user_chunks(user_id)
    # Clear from SQLite metadata only once the vectors are gone
    clear_user_documents(user_id)
    return {"status": "cleared", "deleted": deleted}
