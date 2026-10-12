"""
rag_engine.py — Core RAG pipeline
- Document ingestion: PDF, TXT, MD, DOCX, CSV, XLSX
- Chunking → Gemini Embeddings → ChromaDB vector store (disk-persisted)
- Sequential Chain: Retrieve → Summarize → Generate (LCEL)
- Structured JSON output with confidence scoring
- Conversation memory with multi-turn follow-up support
- Prompt injection protection and context sanitization
"""

from typing import List, Dict, Any



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
from src.llm import llm_client
from src.chunking.chunker import split_documents
from src.ingestion.loader import load_document
from src.vectordb.vector_store import store as _store
from src.retrieval.retriever import retriever, rewrite_question
from src.prompts.prompt_templates import RAG_PROMPT, SUMMARIZE_PROMPT, format_context

# ── Constants ────────────────────────────────────────────────────────────────
TOP_K         = settings.top_k
CONFIDENCE_THRESHOLD = settings.confidence_threshold  # Task 7: minimum cosine similarity to proceed
MEMORY_MAX_TURNS = settings.memory_max_turns  # Task 4: max conversation turns to remember

# ── Task 2: Structured Output Schema ─────────────────────────────────────────

class RAGResponse(BaseModel):
    """Structured response from the RAG pipeline."""
    answer: str = Field(description="The answer to the user's question based on the document context")
    sources: List[Dict[str, Any]] = Field(default_factory=list, description="Source documents used")
    confidence: float = Field(default=0.0, description="Confidence score from 0.0 to 1.0 based on retrieval similarity")

# ── Ingestion ─────────────────────────────────────────────────────────────────

def ingest_document(user_id: int, file_path: str, filename: str) -> Dict[str, Any]:
    """Parse → chunk → embed → store. Returns summary stats."""
    raw_docs = load_document(file_path, filename)
    if not raw_docs:
        raise ValueError("No text could be extracted from the document.")

    chunks = split_documents(raw_docs)

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
        search_query = rewrite_question(question, history)

    if use_hybrid:
        results = retriever.search_hybrid(user_id, search_query, k=TOP_K)
    else:
        results = retriever.search(user_id, search_query, k=TOP_K)

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
        search_query = rewrite_question(question, history)

    if use_hybrid:
        results = retriever.search_hybrid(user_id, search_query, k=TOP_K)
    else:
        results = retriever.search(user_id, search_query, k=TOP_K)

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
    deleted = _store.delete_user_chunks(user_id)
    # Clear from SQLite metadata only once the vectors are gone
    clear_user_documents(user_id)
    return {"status": "cleared", "deleted": deleted}

# ── Session Management ────────────────────────────────────────────────────────

def clear_session(user_id: int, session_id: str):
    """Clear conversation memory for a session."""
    _memory.clear_session(user_id, session_id)


def get_session_history(user_id: int, session_id: str) -> List[Dict[str, str]]:
    """Return conversation history for a session."""
    return _memory.get_history(user_id, session_id)
