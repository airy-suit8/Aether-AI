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

import uuid
from pathlib import Path
from typing import List, Dict, Any

# Task 12: LangChain Document Loaders
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, TextLoader, CSVLoader

# Task 13: LangChain Text Splitters
from langchain_text_splitters import RecursiveCharacterTextSplitter

# LangChain core
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser

# Reuse the existing vector store and memory — no duplication
from rag_engine import (
    _store,
    _memory,
    RAGResponse,
    CONFIDENCE_THRESHOLD,
    TOP_K,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
)

from src.llm import llm_client
from src.prompts.prompt_templates import RAG_PROMPT, REWRITE_PROMPT, SUMMARIZE_PROMPT, format_context


# ── Gemini clients (same models as original) ─────────────────────────────────



# ══════════════════════════════════════════════════════════════════════════════
# Task 12: LangChain Document Loaders
# ══════════════════════════════════════════════════════════════════════════════

def load_document_langchain(file_path: str, filename: str) -> List[Document]:
    """
    Task 12: Use LangChain's official document loaders instead of custom parsers.

    Comparison with original rag_engine.py:
      Original: _parse_pdf() — manual PdfReader loop, 12 lines
      LangChain: PyPDFLoader — 2 lines, handles edge cases automatically

      Original: _parse_docx() — manual python-docx paragraph extraction
      LangChain: Docx2txtLoader — handles tables, headers, footers too

      Original: _parse_text() — manual file.read()
      LangChain: TextLoader — handles encoding detection automatically
    """
    ext = Path(filename).suffix.lower()

    if ext == ".pdf":
        loader = PyPDFLoader(file_path)
    elif ext == ".docx":
        loader = Docx2txtLoader(file_path)
    elif ext in (".txt", ".md", ".markdown"):
        loader = TextLoader(file_path, encoding="utf-8")
    elif ext == ".csv":
        loader = CSVLoader(file_path)
    elif ext in (".xlsx", ".xls"):
        # Use pandas (already a dependency) instead of UnstructuredExcelLoader (1GB+ dep)
        import pandas as pd
        df = pd.read_excel(file_path)
        if df.empty:
            return []
        columns = list(df.columns)
        raw_docs = []
        chunk_lines = []
        for _, row in df.iterrows():
            line = ", ".join(f"{col}: {row[col]}" for col in columns if pd.notna(row[col]))
            chunk_lines.append(line)
            if len(chunk_lines) >= 50:
                raw_docs.append(Document(
                    page_content="\n".join(chunk_lines),
                    metadata={"source": filename, "page": len(raw_docs) + 1, "type": ext.lstrip(".")},
                ))
                chunk_lines = []
        if chunk_lines:
            raw_docs.append(Document(
                page_content="\n".join(chunk_lines),
                metadata={"source": filename, "page": len(raw_docs) + 1, "type": ext.lstrip(".")},
            ))
        return raw_docs
    else:
        raise ValueError(f"Unsupported file type '{ext}'. Allowed: pdf, docx, txt, md, csv, xlsx, xls")

    # LangChain loaders return List[Document] with metadata already populated
    raw_docs = loader.load()

    # Normalize metadata to match our existing format
    for doc in raw_docs:
        doc.metadata["source"] = filename
        if "page" not in doc.metadata:
            doc.metadata["page"] = 1
        doc.metadata["type"] = ext.lstrip(".")

    return raw_docs


# ══════════════════════════════════════════════════════════════════════════════
# Task 13: LangChain Text Splitters
# ══════════════════════════════════════════════════════════════════════════════

def split_documents_langchain(raw_docs: List[Document]) -> List[Document]:
    """
    Task 13: Use RecursiveCharacterTextSplitter as specified in the plan.

    Same splitter as the original pipeline, but used here within the
    standardized LangChain loader → splitter → embedder workflow.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    chunks = splitter.split_documents(raw_docs)

    # Enrich metadata with chunk positioning
    total = len(chunks)
    for i, chunk in enumerate(chunks):
        chunk.metadata["chunk_id"] = str(uuid.uuid4())
        chunk.metadata["chunk_index"] = i + 1
        chunk.metadata["total_chunks"] = total

    return chunks


# ══════════════════════════════════════════════════════════════════════════════
# Ingestion (Tasks 12 + 13 combined)
# ══════════════════════════════════════════════════════════════════════════════

def ingest_document_langchain(user_id: int, file_path: str, filename: str) -> Dict[str, Any]:
    """
    LangChain ingestion pipeline: Loader → Splitter → Embed → Store.

    Uses the SAME vector store as the original pipeline (_store from rag_engine.py)
    so documents are shared between both pipelines.
    """
    # Task 12: Load with LangChain loaders
    raw_docs = load_document_langchain(file_path, filename)
    if not raw_docs:
        raise ValueError("No text could be extracted from the document.")

    # Task 13: Split with LangChain splitter
    chunks = split_documents_langchain(raw_docs)

    # Embed and store (reuses existing vector store)
    _store.add_documents(user_id, chunks)

    return {"filename": filename, "pages": len(raw_docs), "chunks": len(chunks)}


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
        llm = llm_client.get_llm()
        search_query = (REWRITE_PROMPT | llm | StrOutputParser()).invoke({"history": history, "question": question}).strip()

    results = _store.search(user_id, search_query, k=TOP_K)

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
