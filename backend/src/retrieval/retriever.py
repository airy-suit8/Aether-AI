"""
retrieval/retriever.py — find the chunks that answer a question.

  Retriever      dense (cosine) search, BM25 keyword search, and hybrid search that fuses the
                 two with Reciprocal Rank Fusion; every search is filtered by user_id. Dense and
                 hybrid hits are scored by cosine similarity, from 0 to 1
  UserRetriever  the same dense search as a LangChain retriever object (BaseRetriever), used by
                 the "langchain" pipeline strategy (Task 14)
  rewrite_question  turns a follow-up into a standalone question before searching (Task 4)
"""

import math
import re
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

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

# How many users' keyword indexes are kept in memory at once
BM25_USERS_KEPT = 32


def _tokens(text: str) -> List[str]:
    """Lower-case words and numbers; punctuation separates them, so "gate." matches "gate"."""
    return re.findall(r"\w+", text.lower())


def _chunk_key(hit: Dict) -> str:
    """What makes two hits the same chunk: its id (its whole text for a chunk stored without one)."""
    return hit["meta"].get("chunk_id") or hit["text"]


class _Bm25(BM25Okapi):
    """BM25 with an idf that is never negative: log(1 + (N - n + 0.5) / (n + 0.5)), as Lucene uses.

    rank_bm25's own idf is zero or below for a word found in half the chunks or more, so a user
    with one or two chunks got no keyword hits at all (R3).
    """

    def _calc_idf(self, nd):
        for word, freq in nd.items():
            self.idf[word] = math.log(1 + (self.corpus_size - freq + 0.5) / (freq + 0.5))


class Retriever:
    """Searches over one vector store. Each hit is {"text", "meta", "score"}."""

    def __init__(self, store: VectorStore):
        self.store = store
        # user_id -> (store version, index, chunk texts, chunk metadata), most recently used last
        self._bm25: "OrderedDict[int, Tuple[int, Optional[_Bm25], List[str], List[Dict]]]" = OrderedDict()

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

    def _bm25_index(self, user_id: int) -> Tuple[Optional["_Bm25"], List[str], List[Dict]]:
        """The user's keyword index, rebuilt only when their chunks have changed (R3)."""
        version = self.store.version(user_id)
        cached = self._bm25.get(user_id)
        if cached is None or cached[0] != version:
            docs, metas = self.store.get_user_chunks(user_id)
            cached = (version, _Bm25([_tokens(doc) for doc in docs]) if docs else None, docs, metas)
            self._bm25[user_id] = cached
            while len(self._bm25) > BM25_USERS_KEPT:
                self._bm25.popitem(last=False)
        self._bm25.move_to_end(user_id)
        return cached[1:]

    def search_bm25(self, user_id: int, query: str, k: Optional[int] = None) -> List[Dict]:
        """BM25 keyword search over the user's chunks. Scores are BM25 scores, not similarities."""
        k = k or settings.top_k
        index, docs, metas = self._bm25_index(user_id)
        if index is None:
            return []
        scores = index.get_scores(_tokens(query))
        top_indices = np.argsort(scores)[::-1][:k]
        # A score of 0 means the chunk shares no word with the query
        return [
            {"text": docs[idx], "meta": metas[idx], "score": float(scores[idx])}
            for idx in top_indices if scores[idx] > 0
        ]

    def search_hybrid(self, user_id: int, query: str, k: Optional[int] = None, rrf_k: int = 60) -> List[Dict]:
        """
        Dense and BM25 search, merged with Reciprocal Rank Fusion:
        a chunk's fused value is 1 / (rrf_k + its dense rank) + 1 / (rrf_k + its BM25 rank).

        Fusion decides the order only. Each hit's "score" is its cosine similarity to the query,
        the same scale as dense search, so the confidence threshold means the same thing in
        every mode (R2).
        """
        k = k or settings.top_k
        dense_results = self.search(user_id, query, k=k*2)
        bm25_results = self.search_bm25(user_id, query, k=k*2)

        hits, fused = {}, {}
        for ranked in (dense_results, bm25_results):
            for rank, hit in enumerate(ranked, start=1):
                key = _chunk_key(hit)
                hits.setdefault(key, hit)  # dense first: a chunk both found keeps its similarity
                fused[key] = fused.get(key, 0.0) + 1.0 / (rrf_k + rank)
        top = sorted(fused, key=fused.get, reverse=True)[:k]

        # A chunk only the keyword search found carries a BM25 score: look up its similarity
        dense_keys = {_chunk_key(hit) for hit in dense_results}
        keyword_only = [key for key in top if key not in dense_keys]
        similarity = self.store.similarities(
            user_id, query, [hits[key]["meta"]["chunk_id"] for key in keyword_only if "chunk_id" in hits[key]["meta"]],
        ) if keyword_only else {}

        results = []
        for key in top:
            hit = dict(hits[key])
            if key in keyword_only:
                hit["score"] = similarity.get(hit["meta"].get("chunk_id"), 0.0)
            results.append(hit)
        return results


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
