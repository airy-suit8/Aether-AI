"""
vectordb/vector_store.py — the vector store: ChromaDB on disk, one collection, cosine distance.

The store opens on first use, so importing this module opens nothing and needs no API key
(opening it builds the embedding client, which needs the key).
"""

from pathlib import Path
from typing import Dict, List, Tuple

from langchain_chroma import Chroma
from langchain_core.documents import Document

from src.core.config import settings
from src.embeddings import embedder


class VectorStore:
    """
    Every user's chunks in one ChromaDB collection on disk, each tagged with its user_id.
    Every read is filtered by user_id.
    """
    collection_name = "aether_collection"

    def __init__(self):
        self._chroma = None

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

    def add_documents(self, user_id: int, documents: List[Document]):
        """Directly add Document objects to Chroma, tagged with user_id."""
        for doc in documents:
            doc.metadata["user_id"] = user_id
        self.chroma.add_documents(documents)

    def similarity_search(self, user_id: int, query: str, k: int) -> List[Tuple[Document, float]]:
        """The k chunks of one user closest to the query, with cosine similarity scores."""
        return self.chroma.similarity_search_with_relevance_scores(query, k=k, filter={"user_id": user_id})

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
        return len(chunk_ids)


# Module-level singleton — opens the store on first use
store = VectorStore()
