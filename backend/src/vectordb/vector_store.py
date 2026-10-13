"""
vectordb/vector_store.py — the vector store: ChromaDB on disk, one collection, cosine distance.

Each chunk is tagged with its owner's tenant id, a random id from the users table, and every
read is filtered by it (S2). The tenant id is the key, not the integer user id, because user ids
restart in a new database while this store lives on in its own folder.

The store opens on first use, so importing this module opens nothing. Reading, re-tagging and
deleting chunks need no API key; adding and searching do (they embed text).
"""

from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import chromadb
import numpy as np
from langchain_chroma import Chroma
from langchain_core.documents import Document

from src.core.config import settings
from src.embeddings import embedder

# How many recent query embeddings embed_query() keeps
QUERY_VECTORS_KEPT = 32

# Cosine distance, so relevance scores are cosine similarity (Chroma's default is L2). Only
# applies when the collection is created.
COLLECTION_CONFIGURATION = {"hnsw": {"space": "cosine"}}


class VectorStore:
    """Every tenant's chunks in one ChromaDB collection on disk, each tagged with its tenant_id."""
    collection_name = "aether_collection"

    def __init__(self):
        self._client = None
        self._collection = None
        self._chroma = None
        self._versions: Dict[str, int] = {}
        self._query_vectors: "OrderedDict[str, List[float]]" = OrderedDict()

    def _path(self) -> Path:
        return Path(settings.vector_store_dir) / "chroma_db"

    def exists(self) -> bool:
        """True when a store has been created on disk."""
        return (self._path() / "chroma.sqlite3").exists()

    @property
    def collection(self) -> chromadb.Collection:
        """The Chroma collection itself, for reads, metadata updates and deletes (no embedding model needed)."""
        if self._collection is None:
            self._path().mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(self._path()))
            self._collection = self._client.get_or_create_collection(
                self.collection_name, configuration=COLLECTION_CONFIGURATION)
        return self._collection

    @property
    def chroma(self) -> Chroma:
        """The same collection through LangChain, which embeds text: needs the API key."""
        if self._chroma is None:
            self.collection  # opens the client
            self._chroma = Chroma(
                collection_name=self.collection_name,
                embedding_function=embedder.get_embeddings(),
                client=self._client,
                collection_configuration=COLLECTION_CONFIGURATION,
            )
        return self._chroma

    def version(self, tenant: str) -> int:
        """A number that changes whenever this tenant's chunks change, for anything cached from them.

        Kept in this process: the app runs as one server process (as the conversation cache and
        the rate limiter already assume).
        """
        return self._versions.get(tenant, 0)

    def _changed(self, tenant: str) -> None:
        self._versions[tenant] = self._versions.get(tenant, 0) + 1

    def add_documents(self, tenant: str, documents: List[Document]):
        """Directly add Document objects to Chroma, tagged with the tenant id."""
        for doc in documents:
            doc.metadata["tenant_id"] = tenant
        self.chroma.add_documents(documents)
        self._changed(tenant)

    def embed_query(self, query: str) -> List[float]:
        """The query's embedding. The last few are kept, so one question is embedded once even
        when both the search and similarities() need its vector."""
        vector = self._query_vectors.get(query)
        if vector is None:
            vector = self.chroma.embeddings.embed_query(query)
            self._query_vectors[query] = vector
            while len(self._query_vectors) > QUERY_VECTORS_KEPT:
                self._query_vectors.popitem(last=False)
        return vector

    def similarity_search(self, tenant: str, query: str, k: int) -> List[Tuple[Document, float]]:
        """The k chunks of one tenant closest to the query, with cosine similarity scores from 0 to 1."""
        found = self.chroma.similarity_search_by_vector_with_relevance_scores(
            self.embed_query(query), k=k, filter={"tenant_id": tenant})
        # Chroma returns cosine distance. Rounding can put an exact match just above 1, and an
        # opposite vector is below 0; both are clamped so a score is always a share of 1.
        return [(doc, max(0.0, min(1.0, 1.0 - distance))) for doc, distance in found]

    def similarities(self, tenant: str, query: str, chunk_ids: List[str]) -> Dict[str, float]:
        """The cosine similarity (0 to 1) between the query and each named chunk of one tenant."""
        if not chunk_ids:
            return {}
        res = self.collection.get(
            where={"$and": [{"tenant_id": tenant}, {"chunk_id": {"$in": list(chunk_ids)}}]},
            include=["metadatas", "embeddings"],
        )
        query_vector = np.asarray(self.embed_query(query), dtype=float)
        scores = {}
        for meta, vector in zip(res["metadatas"], res["embeddings"]):
            vector = np.asarray(vector, dtype=float)
            norms = float(np.linalg.norm(query_vector) * np.linalg.norm(vector))
            cosine = float(query_vector @ vector) / norms if norms else 0.0
            scores[meta["chunk_id"]] = max(0.0, min(1.0, cosine))
        return scores

    def get_user_chunks(self, tenant: str) -> Tuple[List[str], List[Dict]]:
        """Every chunk text and its metadata for one tenant."""
        res = self.collection.get(where={"tenant_id": tenant}, include=["documents", "metadatas"])
        return res.get("documents", []), res.get("metadatas", [])

    def delete_document_chunks(self, tenant: str, document_id: int, filename: Optional[str] = None) -> int:
        """Delete the chunks of one of a tenant's documents and return how many there were (R7).
        With a filename, chunks of that name stored before documents had ids go too."""
        coll = self.collection
        chunk_ids = coll.get(where={"$and": [{"tenant_id": tenant}, {"document_id": document_id}]}, include=[])["ids"]
        if not chunk_ids and filename:
            # Chunks stored before documents had an id carry only the file name
            named = coll.get(where={"$and": [{"tenant_id": tenant}, {"source": filename}]}, include=["metadatas"])
            chunk_ids = [i for i, meta in zip(named["ids"], named["metadatas"]) if "document_id" not in meta]
        if chunk_ids:
            coll.delete(ids=chunk_ids)
        self._changed(tenant)
        return len(chunk_ids)

    def delete_user_chunks(self, tenant: str) -> int:
        """Delete every chunk of one tenant and return how many there were. Errors propagate."""
        coll = self.collection
        chunk_ids = coll.get(where={"tenant_id": tenant}, include=[])["ids"]
        if chunk_ids:
            coll.delete(where={"tenant_id": tenant})
        self._changed(tenant)
        return len(chunk_ids)

    # ── Every tenant at once, for python -m src.maintenance ───────────────────

    def all_chunks(self) -> Tuple[List[str], List[Dict]]:
        """The ids and metadata of every chunk in the store."""
        res = self.collection.get(include=["metadatas"])
        return res["ids"], res["metadatas"]

    def delete_chunks(self, chunk_ids: List[str]) -> int:
        """Delete chunks by id, whichever tenant they belong to. Returns how many were asked for."""
        if chunk_ids:
            tenants = {meta.get("tenant_id") for meta in self.collection.get(ids=list(chunk_ids), include=["metadatas"])["metadatas"]}
            self.collection.delete(ids=list(chunk_ids))
            for tenant in tenants - {None}:
                self._changed(tenant)
        return len(chunk_ids)

    # ── Chunks stored before tenant ids (keyed by the integer user_id) ────────

    def chunks_without_tenant(self) -> Tuple[List[str], List[Dict]]:
        """The ids and metadata of chunks still keyed by an integer user_id."""
        res = self.collection.get(where={"user_id": {"$gte": 0}}, include=["metadatas"])
        return res["ids"], res["metadatas"]

    def set_tenants(self, tenants: Dict[str, str]) -> None:
        """Re-key chunks: give each chunk id its tenant id and drop its user_id."""
        if not tenants:
            return
        ids = list(tenants)
        self.collection.update(ids=ids, metadatas=[{"tenant_id": tenants[i], "user_id": None} for i in ids])
        for tenant in set(tenants.values()):
            self._changed(tenant)


# Module-level singleton — opens the store on first use
store = VectorStore()
