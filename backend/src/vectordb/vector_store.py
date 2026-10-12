"""
vectordb/vector_store.py — the vector store: ChromaDB on disk, one collection, cosine distance.

The store opens on first use, so importing this module opens nothing and needs no API key
(opening it builds the embedding client, which needs the key).
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from langchain_chroma import Chroma
from langchain_core.documents import Document
from rank_bm25 import BM25Okapi

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

    def search(self, user_id: int, query: str, k: Optional[int] = None) -> List[Dict]:
        """Search by text query, filtered by user_id."""
        k = k or settings.top_k
        results = self.chroma.similarity_search_with_relevance_scores(query, k=k, filter={"user_id": user_id})
        formatted = []
        for doc, score in results:
            formatted.append({
                "text": doc.page_content,
                "meta": doc.metadata,
                "score": float(score),
            })
        return formatted

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

    def search_bm25(self, user_id: int, query: str, k: Optional[int] = None) -> List[Dict]:
        """Perform BM25 sparse keyword search on user's documents."""
        k = k or settings.top_k
        try:
            docs, metas = self.get_user_chunks(user_id)
            if not docs:
                return []
            
            tokenized_corpus = [doc.lower().split() for doc in docs]
            bm25 = BM25Okapi(tokenized_corpus)
            tokenized_query = query.lower().split()
            scores = bm25.get_scores(tokenized_query)
            
            top_indices = np.argsort(scores)[::-1][:k]
            results = []
            for idx in top_indices:
                if scores[idx] > 0:
                    results.append({
                        "text": docs[idx],
                        "meta": metas[idx],
                        "score": float(scores[idx]),
                    })
            return results
        except Exception:
            return []

    def search_hybrid(self, user_id: int, query: str, k: Optional[int] = None, rrf_k: int = 60) -> List[Dict]:
        """
        Reciprocal Rank Fusion (RRF) combining Dense Vector Search & BM25 Sparse Search.
        RRF Score = 1 / (rrf_k + rank_dense) + 1 / (rrf_k + rank_bm25)
        """
        k = k or settings.top_k
        dense_results = self.search(user_id, query, k=k*2)
        bm25_results = self.search_bm25(user_id, query, k=k*2)
        
        if not dense_results and not bm25_results:
            return []
        if not bm25_results:
            return dense_results[:k]
        if not dense_results:
            return bm25_results[:k]

        rrf_scores = {}
        doc_map = {}
        
        for rank, r in enumerate(dense_results, start=1):
            key = r["text"][:120]
            doc_map[key] = r
            rrf_scores[key] = rrf_scores.get(key, 0.0) + (1.0 / (rrf_k + rank))
            
        for rank, r in enumerate(bm25_results, start=1):
            key = r["text"][:120]
            doc_map[key] = r
            rrf_scores[key] = rrf_scores.get(key, 0.0) + (1.0 / (rrf_k + rank))
            
        sorted_keys = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)[:k]
        
        final_results = []
        for key in sorted_keys:
            item = doc_map[key].copy()
            # Normalize RRF score relative to max theoretical RRF score (2 / (rrf_k + 1))
            normalized_score = round(rrf_scores[key] / (2.0 / (rrf_k + 1)), 3)
            item["score"] = max(0.1, min(1.0, normalized_score))
            final_results.append(item)
            
        return final_results


# Module-level singleton — opens the store on first use
store = VectorStore()
