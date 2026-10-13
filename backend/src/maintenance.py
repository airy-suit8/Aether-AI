"""
maintenance.py — what the vector store and the database disagree on, reported, and removed when
asked (Sprint 8, item 6).

Run from backend/, with the backend stopped:
  python -m src.maintenance            report only: nothing is deleted
  python -m src.maintenance --apply    report, then delete what was reported

It reports two things:
  chunks no document record accounts for   left behind when a database was reset, or by a
                                           delete that removed a record but not its chunks.
                                           The startup log counts them; until now nothing
                                           removed them.
  document records with no chunks          a document listed as ready that nothing can be
                                           found in, such as a record kept from before the
                                           vector store was recreated
A record still being read is left alone (its chunks are on their way), and so is one that
failed (its owner sees it in the library and can remove it).

A chunk belongs to a record when it carries that record's tenant and document id; one stored
before documents had ids, its tenant and file name; one stored before tenant ids, the record's
user id and file name (as the startup's migration files them, pipeline/documents.py).
"""

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.core.config import settings
from src.db.database import delete_document_record, get_document_owners, init_db
from src.vectordb.vector_store import store


def _record_key(meta: Dict[str, Any]) -> Optional[Tuple]:
    """Which record a chunk's metadata names: by tenant and document id, else by name."""
    tenant, document_id, name = meta.get("tenant_id"), meta.get("document_id"), meta.get("source")
    if tenant is None:
        # Not yet filed under a tenant: named by the integer user id it was stored with
        return ("user", meta.get("user_id"), document_id, name) if document_id is not None else ("user", meta.get("user_id"), name)
    return ("tenant", tenant, document_id) if document_id is not None else ("tenant", tenant, name)


def _keys_of(record: Dict[str, Any]) -> List[Tuple]:
    """Every key a chunk of this record may carry."""
    return [
        ("tenant", record["tenant_id"], record["document_id"]),
        ("tenant", record["tenant_id"], record["filename"]),
        ("user", record["user_id"], record["document_id"], record["filename"]),
        ("user", record["user_id"], record["filename"]),
    ]


def find() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(chunks no record accounts for, ready records with no chunks)."""
    records = get_document_owners()
    owner_of = {key: record["document_id"] for record in records for key in _keys_of(record)}
    ids, metas = store.all_chunks()
    orphans, used = [], set()
    for chunk_id, meta in zip(ids, metas):
        document = owner_of.get(_record_key(meta))
        if document is None:
            orphans.append({"id": chunk_id, "source": meta.get("source"), "document_id": meta.get("document_id"),
                            "tenant_id": meta.get("tenant_id")})
        else:
            used.add(document)
    empty = [r for r in records if r["status"] == "ready" and r["document_id"] not in used]
    return orphans, empty


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Report chunks no document accounts for and documents with no chunks.")
    parser.add_argument("--apply", action="store_true", help="delete what is reported (without it, nothing is deleted)")
    args = parser.parse_args(argv)
    if not Path(settings.db_path).is_file():
        print(f"No database at {settings.db_path}.", file=sys.stderr)
        return 1
    if not store.exists():
        # Every record would look empty: say so rather than offer to delete them all
        print(f"No vector store at {settings.vector_store_dir}, so there is nothing to compare the records with.",
              file=sys.stderr)
        return 1
    init_db()  # the same table upgrades the backend makes when it starts

    orphans, empty = find()
    print(f"Database: {settings.db_path}\nVector store: {settings.vector_store_dir}\n")
    print(f"Chunks no document record accounts for: {len(orphans)}")
    for chunk in orphans:
        document = "no document id" if chunk["document_id"] is None else f"document {chunk['document_id']}"
        owner = f"tenant {chunk['tenant_id']}" if chunk["tenant_id"] else "no tenant"
        print(f"  chunk {chunk['id']}: {chunk['source'] or 'no file name'}, {document}, {owner}")
    print(f"Document records with no chunks: {len(empty)}")
    for record in empty:
        print(f"  record {record['document_id']}: {record['filename']}, user {record['user_id']}, added {record['uploaded_at']}")

    if not orphans and not empty:
        print("\nNothing to tidy.")
        return 0
    if not args.apply:
        print("\nNothing was deleted. Run again with --apply to delete the chunks and records listed above.")
        return 0
    deleted = store.delete_chunks([chunk["id"] for chunk in orphans])
    for record in empty:
        delete_document_record(record["user_id"], record["document_id"])
    print(f"\nDeleted {deleted} chunk{'' if deleted == 1 else 's'} and {len(empty)} record{'' if len(empty) == 1 else 's'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
