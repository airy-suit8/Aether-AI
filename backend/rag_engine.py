"""
rag_engine.py — Core RAG pipeline
- Document ingestion: PDF, TXT, MD, DOCX, CSV, XLSX
- Chunking → Gemini Embeddings → ChromaDB vector store (disk-persisted)
- Sequential Chain: Retrieve → Summarize → Generate (LCEL)
- Structured JSON output with confidence scoring
- Conversation memory with multi-turn follow-up support
- Prompt injection protection and context sanitization
"""

import uuid
from pathlib import Path
from typing import List, Dict, Any

import numpy as np
from rank_bm25 import BM25Okapi


from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser

from pydantic import BaseModel, Field

from src.db.database import (
    save_conversation,
    get_conversation_history,
    clear_conversation as db_clear_conversation,
    clear_user_documents,
    get_all_documents_detailed as _db_get_all_documents_detailed,
)

from src.core.config import settings
from src.embeddings import embedder
from src.llm import llm_client
from src.ingestion.loader import load_document
from src.prompts.prompt_templates import RAG_PROMPT, REWRITE_PROMPT, SUMMARIZE_PROMPT, format_context

# ── Constants ────────────────────────────────────────────────────────────────
STORE_DIR     = Path(settings.vector_store_dir)
CHUNK_SIZE    = settings.chunk_size
CHUNK_OVERLAP = settings.chunk_overlap
TOP_K         = settings.top_k
CONFIDENCE_THRESHOLD = settings.confidence_threshold  # Task 7: minimum cosine similarity to proceed
MEMORY_MAX_TURNS = settings.memory_max_turns  # Task 4: max conversation turns to remember

STORE_DIR.mkdir(parents=True, exist_ok=True)

# ── Gemini clients ────────────────────────────────────────────────────────────


# ── Task 2: Structured Output Schema ─────────────────────────────────────────

class RAGResponse(BaseModel):
    """Structured response from the RAG pipeline."""
    answer: str = Field(description="The answer to the user's question based on the document context")
    sources: List[Dict[str, Any]] = Field(default_factory=list, description="Source documents used")
    confidence: float = Field(default=0.0, description="Confidence score from 0.0 to 1.0 based on retrieval similarity")

# ── Chroma Vector Store ──────────────────────────────────────────────────────

class ChromaVectorStoreWrapper:
    """
    Production-grade vector store using ChromaDB.
    Persists to disk seamlessly and replaces the legacy numpy store.
    """
    def __init__(self):
        self.persist_directory = str(STORE_DIR / "chroma_db")
        self.collection_name = "aether_collection"
        self._chroma = None

    @property
    def chroma(self) -> Chroma:
        """Open the store on first use, so importing this module needs no API key."""
        if self._chroma is None:
            self._init_chroma()
        return self._chroma

    def _init_chroma(self):
        self._chroma = Chroma(
            collection_name=self.collection_name,
            embedding_function=embedder.get_embeddings(),
            persist_directory=self.persist_directory,
            # Cosine distance, so relevance scores are cosine similarity (Chroma's default is L2).
            # Only applies when the collection is created: delete an old vector_store/ to switch.
            collection_configuration={"hnsw": {"space": "cosine"}},
        )

    def add_documents(self, user_id: int, documents: List[Document]):
        """Directly add Document objects to Chroma, tagged with user_id."""
        for doc in documents:
            doc.metadata["user_id"] = user_id
        self.chroma.add_documents(documents)

    def search(self, user_id: int, query: str, k: int = TOP_K) -> List[Dict]:
        """Search by text query, filtered by user_id."""
        results = self.chroma.similarity_search_with_relevance_scores(query, k=k, filter={"user_id": user_id})
        formatted = []
        for doc, score in results:
            formatted.append({
                "text": doc.page_content,
                "meta": doc.metadata,
                "score": float(score),
            })
        return formatted

    def search_bm25(self, user_id: int, query: str, k: int = TOP_K) -> List[Dict]:
        """Perform BM25 sparse keyword search on user's documents."""
        try:
            coll = self.chroma._collection
            res = coll.get(where={"user_id": user_id}, include=["documents", "metadatas"])
            docs = res.get("documents", [])
            metas = res.get("metadatas", [])
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

    def search_hybrid(self, user_id: int, query: str, k: int = TOP_K, rrf_k: int = 60) -> List[Dict]:
        """
        Reciprocal Rank Fusion (RRF) combining Dense Vector Search & BM25 Sparse Search.
        RRF Score = 1 / (rrf_k + rank_dense) + 1 / (rrf_k + rank_bm25)
        """
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
_store = ChromaVectorStoreWrapper()

# ── Ingestion ─────────────────────────────────────────────────────────────────

def ingest_document(user_id: int, file_path: str, filename: str) -> Dict[str, Any]:
    """Parse → chunk → embed → store. Returns summary stats."""
    raw_docs = load_document(file_path, filename)
    if not raw_docs:
        raise ValueError("No text could be extracted from the document.")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = splitter.split_documents(raw_docs)

    for c in chunks:
        c.metadata["chunk_id"] = str(uuid.uuid4())

    _store.add_documents(user_id, chunks)

    return {"filename": filename, "pages": len(raw_docs), "chunks": len(chunks)}

# ── Task 4: Conversation Memory (SQLite-backed) ──────────────────────────────

class ConversationMemory:
    """
    Conversation buffer — backed by SQLite for persistence.
    In-memory cache is kept for fast reads during a session.
    Every turn is also saved to disk so conversations survive server restarts.
    """

    def __init__(self):
        self._cache: Dict[str, List[Dict[str, str]]] = {}

    @staticmethod
    def _cache_key(user_id: int, session_id: str) -> str:
        """Composite key prevents cross-tenant data leaks when session IDs collide."""
        return f"{user_id}:{session_id}"

    def get_history(self, user_id: int, session_id: str) -> List[Dict[str, str]]:
        """Return list of {"question": ..., "answer": ...} for this session."""
        key = self._cache_key(user_id, session_id)
        if key not in self._cache:
            self._cache[key] = get_conversation_history(user_id, session_id, limit=MEMORY_MAX_TURNS)
        return self._cache.get(key, [])

    def add_turn(self, user_id: int, session_id: str, question: str, answer: str, confidence: float = 0.0, mode: str = "original"):
        """Append a Q&A turn to both cache and SQLite."""
        key = self._cache_key(user_id, session_id)
        if key not in self._cache:
            self._cache[key] = get_conversation_history(user_id, session_id, limit=MEMORY_MAX_TURNS)
        self._cache[key].append({"question": question, "answer": answer})
        # Trim cache
        if len(self._cache[key]) > MEMORY_MAX_TURNS:
            self._cache[key] = self._cache[key][-MEMORY_MAX_TURNS:]
        # Persist to SQLite
        save_conversation(user_id, session_id, question, answer, confidence, mode)

    def clear_session(self, user_id: int, session_id: str):
        """Clear history from both cache and SQLite."""
        key = self._cache_key(user_id, session_id)
        self._cache.pop(key, None)
        db_clear_conversation(user_id, session_id)

    def format_history(self, user_id: int, session_id: str) -> str:
        """Format history into a readable string for the prompt."""
        history = self.get_history(user_id, session_id)
        if not history:
            return "(No previous conversation)"
        lines = []
        for turn in history:
            lines.append(f"User: {turn['question']}")
            lines.append(f"Assistant: {turn['answer']}")
        return "\n".join(lines)


# Module-level singleton
_memory = ConversationMemory()

# ── Task 3: Sequential Chain Query (Retrieve → Summarize → Generate) ─────────

def query_rag(user_id: int, question: str, session_id: str = "default", use_hybrid: bool = False,
              save_turn: bool = True) -> Dict[str, Any]:
    """
    3-step sequential chain using LCEL:
      1. RETRIEVE — embed question → cosine/hybrid search → top-k chunks
      2. SUMMARIZE — condense raw chunks into a focused summary
      3. GENERATE — produce the final answer from the summary
    Returns structured JSON with answer, sources, and confidence.
    save_turn=False is for callers that save the turn themselves (the agent's document search).
    """

    # Contextualize the question for vector search if there's history
    history = _memory.format_history(user_id, session_id)
    search_query = question
    
    if history != "(No previous conversation)":
        llm = llm_client.get_llm()
        search_query = (REWRITE_PROMPT | llm | StrOutputParser()).invoke({"history": history, "question": question}).strip()

    if use_hybrid:
        results = _store.search_hybrid(user_id, search_query, k=TOP_K)
    else:
        results = _store.search(user_id, search_query, k=TOP_K)

    if not results:
        return RAGResponse(
            answer="No documents have been uploaded yet. Please upload some documents first.",
            sources=[],
            confidence=0.0,
        ).model_dump()

    # Task 2: Compute confidence from average cosine similarity
    scores = [r["score"] for r in results]
    confidence = round(sum(scores) / len(scores), 3)
    best_score = max(scores)

    # Task 7: Confidence threshold — refuse if similarity too low
    if best_score < CONFIDENCE_THRESHOLD:
        return RAGResponse(
            answer="I could not find relevant information in the uploaded documents to answer that question.",
            sources=[],
            confidence=confidence,
        ).model_dump()

    # Build context from retrieved chunks (with injection protection)
    raw_context = format_context(results)

    # ── Step 2: Summarize (LCEL chain) ────────────────────────────────────────
    llm = llm_client.get_llm()
    summarize_chain = SUMMARIZE_PROMPT | llm | StrOutputParser()
    summarized_context = summarize_chain.invoke({
        "context": raw_context,
        "question": question,
    })

    # ── Step 3: Generate final answer (LCEL chain) ────────────────────────────
    chat_history = _memory.format_history(user_id, session_id)
    generate_chain = RAG_PROMPT | llm | StrOutputParser()
    answer = generate_chain.invoke({
        "context": summarized_context,
        "question": question,
        "chat_history": chat_history,
    })

    # Build source list
    sources, seen = [], set()
    for r in results:
        src  = r["meta"].get("source", "Unknown")
        page = r["meta"].get("page", "?")
        key  = f"{src}::{page}"
        if key not in seen:
            seen.add(key)
            snippet = r["text"]
            sources.append({
                "source":  src,
                "page":    page,
                "snippet": snippet[:300] + ("…" if len(snippet) > 300 else ""),
                "score":   round(r["score"], 3),
            })

    # Store turn in memory
    if save_turn:
        _memory.add_turn(user_id, session_id, question, answer, confidence, mode="hybrid" if use_hybrid else "original")

    return RAGResponse(
        answer=answer,
        sources=sources,
        confidence=confidence,
    ).model_dump()


def query_rag_stream(user_id: int, question: str, session_id: str = "default", use_hybrid: bool = False):
    """
    Streaming version of the 3-step sequential chain using LCEL.
    Yields dicts with 'type': 'token'/'done'.
    """
    history = _memory.format_history(user_id, session_id)
    search_query = question
    
    if history != "(No previous conversation)":
        llm = llm_client.get_llm()
        search_query = (REWRITE_PROMPT | llm | StrOutputParser()).invoke({"history": history, "question": question}).strip()

    if use_hybrid:
        results = _store.search_hybrid(user_id, search_query, k=TOP_K)
    else:
        results = _store.search(user_id, search_query, k=TOP_K)

    if not results:
        yield {"type": "token", "content": "No documents have been uploaded yet. Please upload some documents first."}
        yield {"type": "done", "sources": [], "confidence": 0.0}
        return

    scores = [r["score"] for r in results]
    confidence = round(sum(scores) / len(scores), 3)
    best_score = max(scores)

    if best_score < CONFIDENCE_THRESHOLD:
        yield {"type": "token", "content": "I could not find relevant information in the uploaded documents to answer that question."}
        yield {"type": "done", "sources": [], "confidence": confidence}
        return

    raw_context = format_context(results)

    llm = llm_client.get_llm()
    summarize_chain = SUMMARIZE_PROMPT | llm | StrOutputParser()
    summarized_context = summarize_chain.invoke({
        "context": raw_context,
        "question": question,
    })

    chat_history = _memory.format_history(user_id, session_id)
    generate_chain = RAG_PROMPT | llm | StrOutputParser()
    
    answer_text = ""
    for chunk in generate_chain.stream({
        "context": summarized_context,
        "question": question,
        "chat_history": chat_history,
    }):
        answer_text += chunk
        yield {"type": "token", "content": chunk}

    sources, seen = [], set()
    for r in results:
        src  = r["meta"].get("source", "Unknown")
        page = r["meta"].get("page", "?")
        key  = f"{src}::{page}"
        if key not in seen:
            seen.add(key)
            snippet = r["text"]
            sources.append({
                "source":  src,
                "page":    page,
                "snippet": snippet[:300] + ("…" if len(snippet) > 300 else ""),
                "score":   round(r["score"], 3),
            })

    _memory.add_turn(user_id, session_id, question, answer_text, confidence, mode="hybrid" if use_hybrid else "original")
    yield {"type": "done", "sources": sources, "confidence": confidence}

# ── Document List & Clear ─────────────────────────────────────────────────────

def list_documents(user_id: int) -> List[str]:
    """List distinct document filenames for a user from SQLite."""
    docs = _db_get_all_documents_detailed(user_id)
    return sorted(list(set(d["filename"] for d in docs)))

def clear_documents(user_id: int) -> Dict[str, Any]:
    """Delete a user's documents from ChromaDB, then SQLite. Returns the number of chunks deleted."""
    # Clear from ChromaDB vector store (errors propagate: the caller reports them)
    coll = _store.chroma._collection
    chunk_ids = coll.get(where={"user_id": user_id}, include=[])["ids"]
    if chunk_ids:
        coll.delete(where={"user_id": user_id})
    # Clear from SQLite metadata only once the vectors are gone
    clear_user_documents(user_id)
    return {"status": "cleared", "deleted": len(chunk_ids)}

# ── Session Management ────────────────────────────────────────────────────────

def clear_session(user_id: int, session_id: str):
    """Clear conversation memory for a session."""
    _memory.clear_session(user_id, session_id)


def get_session_history(user_id: int, session_id: str) -> List[Dict[str, str]]:
    """Return conversation history for a session."""
    return _memory.get_history(user_id, session_id)
