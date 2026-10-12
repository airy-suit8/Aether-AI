"""
retrieval/retriever.py — find the chunks that answer a question.

  Retriever      dense (cosine) search, BM25 keyword search, and hybrid search that fuses the
                 two with Reciprocal Rank Fusion; every search is filtered by user_id
  UserRetriever  the same dense search as a LangChain retriever object (BaseRetriever), used by
                 the "langchain" pipeline strategy (Task 14)
  rewrite_question  turns a follow-up into a standalone question before searching (Task 4)
"""

from typing import Dict, List, Optional

import numpy as np
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.retrievers import BaseRetriever
from rank_bm25 import BM25Okapi

from src.core.config import settings
from src.llm import llm_client
from src.prompts.prompt_templates import REWRITE_PROMPT
from src.vectordb.vector_store import VectorStore, store


class Retriever:
    """Searches over one vector store. Each hit is {"text", "meta", "score"}."""

    def __init__(self, store: VectorStore):
        self.store = store

    def search(self, user_id: int, query: str, k: Optional[int] = None) -> List[Dict]:
        """Search by text query, filtered by user_id."""
        k = k or settings.top_k
        results = self.store.similarity_search(user_id, query, k=k)
        formatted = []
        for doc, score in results:
            formatted.append({
                "text": doc.page_content,
                "meta": doc.metadata,
                "score": float(score),
            })
        return formatted

    def search_bm25(self, user_id: int, query: str, k: Optional[int] = None) -> List[Dict]:
        """Perform BM25 sparse keyword search on user's documents."""
        k = k or settings.top_k
        try:
            docs, metas = self.store.get_user_chunks(user_id)
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


# Module-level singleton over the app's vector store
retriever = Retriever(store)


class UserRetriever(BaseRetriever):
    """One user's dense search as a LangChain retriever. Each Document carries its score in metadata["score"]."""

    user_id: int
    k: int

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun) -> List[Document]:
        return [
            Document(page_content=hit["text"], metadata={**hit["meta"], "score": hit["score"]})
            for hit in retriever.search(self.user_id, query, k=self.k)
        ]


def rewrite_question(question: str, history: str, config: Optional[Dict] = None) -> str:
    """Rephrase a follow-up as a standalone question, using the formatted conversation history."""
    llm = llm_client.get_llm()
    return (REWRITE_PROMPT | llm | StrOutputParser()).invoke({"history": history, "question": question}, config=config).strip()
