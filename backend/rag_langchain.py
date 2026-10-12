"""
rag_langchain.py — Phase 5: Experimental LangChain RAG Pipeline

This is a SEPARATE, PARALLEL implementation of the RAG pipeline using
LangChain's official components. The original rag_engine.py is untouched.

Tasks covered:
  Task 12: LangChain Document Loaders (PyPDFLoader, Docx2txtLoader, TextLoader)
  Task 13: LangChain Text Splitters (RecursiveCharacterTextSplitter)
  Task 14: RetrievalQA Chain (Question → Retriever → LLM → Answer)
  Task 15: LCEL Refactor (prompt | model | parser)
"""

from typing import Dict, Any

# LangChain core
from langchain_core.output_parsers import StrOutputParser

# Reuse the existing vector store and memory — no duplication
from rag_engine import (
    _memory,
    RAGResponse,
    CONFIDENCE_THRESHOLD,
    TOP_K,
)

from src.llm import llm_client
from src.retrieval.retriever import retriever, rewrite_question
from src.prompts.prompt_templates import RAG_PROMPT, SUMMARIZE_PROMPT, format_context


# ── Gemini clients (same models as original) ─────────────────────────────────



# ══════════════════════════════════════════════════════════════════════════════
# Task 12: LangChain Document Loaders
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# Task 14 & 15: RetrievalQA Chain with LCEL
# ══════════════════════════════════════════════════════════════════════════════

def _retrieve_and_format(user_id: int, question: str, session_id: str) -> Dict[str, Any]:
    """
    Task 14: Retrieval step — embed the question, search the vector store,
    format results with injection protection and <document> wrapping.

    Returns a dict with formatted context, raw results, scores, and confidence.
    """
    # Contextualize the question for vector search if there's history
    history = _memory.format_history(user_id, session_id)
    search_query = question
    
    if history != "(No previous conversation)":
        search_query = rewrite_question(question, history)

    results = retriever.search(user_id, search_query, k=TOP_K)

    if not results:
        return {
            "context": "",
            "results": [],
            "scores": [],
            "confidence": 0.0,
            "best_score": 0.0,
        }

    scores = [r["score"] for r in results]
    confidence = round(sum(scores) / len(scores), 3)
    best_score = max(scores)


    return {
        "context": format_context(results),
        "results": results,
        "scores": scores,
        "confidence": confidence,
        "best_score": best_score,
    }


def query_rag_langchain(user_id: int, question: str, session_id: str = "default") -> Dict[str, Any]:
    """
    Task 14 + 15: RetrievalQA Chain using LCEL pipe syntax.

    Pipeline:
      Question
        → Retrieve (embed + cosine search)
        → Summarize (prompt | model | parser)
        → Generate  (prompt | model | parser)
        → Structured Response

    This is the LCEL refactor — each step is composed with the | operator.
    """

    # ── Step 1: Retrieve ──────────────────────────────────────────────────────
    retrieval = _retrieve_and_format(user_id, question, session_id)

    if not retrieval["results"]:
        return RAGResponse(
            answer="No documents have been uploaded yet. Please upload some documents first.",
            sources=[],
            confidence=0.0,
        ).model_dump()

    # Confidence threshold check
    if retrieval["best_score"] < CONFIDENCE_THRESHOLD:
        return RAGResponse(
            answer="I could not find relevant information in the uploaded documents to answer that question.",
            sources=[],
            confidence=retrieval["confidence"],
        ).model_dump()

    # ── Step 2: Summarize — Task 15 LCEL syntax (prompt | model | parser) ─────
    llm = llm_client.get_llm()

    summarize_chain = SUMMARIZE_PROMPT | llm | StrOutputParser()

    summarized_context = summarize_chain.invoke({
        "context": retrieval["context"],
        "question": question,
    })

    # ── Step 3: Generate — Task 15 LCEL syntax (prompt | model | parser) ──────
    chat_history = _memory.format_history(user_id, session_id)

    generate_chain = RAG_PROMPT | llm | StrOutputParser()

    answer = generate_chain.invoke({
        "context": summarized_context,
        "question": question,
        "chat_history": chat_history,
    })

    # ── Build source list ─────────────────────────────────────────────────────
    sources, seen = [], set()
    for r in retrieval["results"]:
        src = r["meta"].get("source", "Unknown")
        page = r["meta"].get("page", "?")
        key = f"{src}::{page}"
        if key not in seen:
            seen.add(key)
            snippet = r["text"]
            sources.append({
                "source": src,
                "page": page,
                "snippet": snippet[:300] + ("…" if len(snippet) > 300 else ""),
                "score": round(r["score"], 3),
            })

    # Store turn in memory
    _memory.add_turn(user_id, session_id, question, answer, retrieval["confidence"], mode="langchain")

    return RAGResponse(
        answer=answer,
        sources=sources,
        confidence=retrieval["confidence"],
    ).model_dump()


def query_rag_langchain_stream(user_id: int, question: str, session_id: str = "default"):
    """
    Streaming version of the RetrievalQA Chain using LCEL.
    Yields dicts with 'type': 'token'/'done'.
    """
    retrieval = _retrieve_and_format(user_id, question, session_id)

    if not retrieval["results"]:
        yield {"type": "token", "content": "No documents have been uploaded yet. Please upload some documents first."}
        yield {"type": "done", "sources": [], "confidence": 0.0}
        return

    if retrieval["best_score"] < CONFIDENCE_THRESHOLD:
        yield {"type": "token", "content": "I could not find relevant information in the uploaded documents to answer that question."}
        yield {"type": "done", "sources": [], "confidence": retrieval["confidence"]}
        return

    llm = llm_client.get_llm()
    summarize_chain = SUMMARIZE_PROMPT | llm | StrOutputParser()

    summarized_context = summarize_chain.invoke({
        "context": retrieval["context"],
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
    for r in retrieval["results"]:
        src = r["meta"].get("source", "Unknown")
        page = r["meta"].get("page", "?")
        key = f"{src}::{page}"
        if key not in seen:
            seen.add(key)
            snippet = r["text"]
            sources.append({
                "source": src,
                "page": page,
                "snippet": snippet[:300] + ("…" if len(snippet) > 300 else ""),
                "score": round(r["score"], 3),
            })

    _memory.add_turn(user_id, session_id, question, answer_text, retrieval["confidence"], mode="langchain")
    yield {"type": "done", "sources": sources, "confidence": retrieval["confidence"]}
