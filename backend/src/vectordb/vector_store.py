"""
vectordb/vector_store.py — the vector store: ChromaDB on disk, one collection, cosine distance.

The store opens on first use, so importing this module opens nothing and needs no API key
(opening it builds the embedding client, which needs the key).
"""

from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
from langchain_chroma import Chroma
from langchain_core.documents import Document

from src.core.config import settings
from src.embeddings import embedder

# How many recent query embeddings embed_query() keeps
QUERY_VECTORS_KEPT = 32


class VectorStore:
    """
    Every user's chunks in one ChromaDB collection on disk, each tagged with its user_id.
    Every read is filtered by user_id.
    """
    collection_name = "aether_collection"

    def __init__(self):
        self._chroma = None
        self._versions: Dict[int, int] = {}
        self._query_vectors: "OrderedDict[str, List[float]]" = OrderedDict()

    @property
    def chroma(self) -> Chroma:
        """Open the store on first use, so importing this module needs no API key."""
        if self._chroma is None:
            self._init_chroma()
        return self._chroma

    def _init_chroma(self):
        store_dir = Path(settings.vector_store_dir)
        store_dir.mkdir(parents=True, exist_ok=True)
        self._chroma = Chroma(
            collection_name=self.collection_name,
            embedding_function=embedder.get_embeddings(),
            persist_directory=str(store_dir / "chroma_db"),
            # Cosine distance, so relevance scores are cosine similarity (Chroma's default is L2).
            # Only applies when the collection is created: delete an old vector_store/ to switch.
            collection_configuration={"hnsw": {"space": "cosine"}},
        )

    def version(self, user_id: int) -> int:
        """A number that changes whenever this user's chunks change, for anything cached from them.

        Kept in this process: the app runs as one server process (as the conversation cache and
        the rate limiter already assume).
        """
        return self._versions.get(user_id, 0)

    def _changed(self, user_id: int) -> None:
        self._versions[user_id] = self._versions.get(user_id, 0) + 1

    def add_documents(self, user_id: int, documents: List[Document]):
        """Directly add Document objects to Chroma, tagged with user_id."""
        for doc in documents:
            doc.metadata["user_id"] = user_id
        self.chroma.add_documents(documents)
        self._changed(user_id)

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

    def similarity_search(self, user_id: int, query: str, k: int) -> List[Tuple[Document, float]]:
        """The k chunks of one user closest to the query, with cosine similarity scores from 0 to 1."""
        found = self.chroma.similarity_search_by_vector_with_relevance_scores(
            self.embed_query(query), k=k, filter={"user_id": user_id})
        # Chroma returns cosine distance. Rounding can put an exact match just above 1, and an
        # opposite vector is below 0; both are clamped so a score is always a share of 1.
        return [(doc, max(0.0, min(1.0, 1.0 - distance))) for doc, distance in found]

    def similarities(self, user_id: int, query: str, chunk_ids: List[str]) -> Dict[str, float]:
        """The cosine similarity (0 to 1) between the query and each named chunk of one user."""
        if not chunk_ids:
            return {}
        res = self.chroma._collection.get(
            where={"$and": [{"user_id": user_id}, {"chunk_id": {"$in": list(chunk_ids)}}]},
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

    def get_user_chunks(self, user_id: int) -> Tuple[List[str], List[Dict]]:
        """Every chunk text and its metadata for one user."""
        res = self.chroma._collection.get(where={"user_id": user_id}, include=["documents", "metadatas"])
        return res.get("documents", []), res.get("metadatas", [])

    def delete_user_chunks(self, user_id: int) -> int:
        """Delete every chunk of one user and return how many there were. Errors propagate."""
        coll = self.chroma._collection
        chunk_ids = coll.get(where={"user_id": user_id}, include=[])["ids"]
        if chunk_ids:
            coll.delete(where={"user_id": user_id})
        self._changed(user_id)
        return len(chunk_ids)


# Module-level singleton — opens the store on first use
store = VectorStore()
