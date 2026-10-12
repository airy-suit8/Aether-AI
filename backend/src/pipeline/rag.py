"""
pipeline/rag.py — the one question-answering pipeline.

events() yields what the client sees, in order:
  {"type": "token", "content": str}                      zero or more pieces of the answer
  {"type": "done", "sources": [...], "confidence": float}  last; agent answers add "tool_used"
The streaming route sends each event as it comes; answer() collects them for the plain route.
Errors are raised, not yielded: each route reports them in its own way.

One pipeline, four modes:
  default    rewrite a follow-up -> dense search -> summarize -> answer (Task 3, LCEL)
  hybrid     the same, with hybrid (dense + BM25) search
  langchain  Tasks 14-15: retrieval through a LangChain retriever object (UserRetriever), and
             summarize -> answer composed as one LCEL chain (RetrievalQA style)
  agent      the tool-calling agent (Task 11); its document search runs this pipeline in
             default mode without saving a turn
Every mode shares the prompts, the memory, the confidence threshold and the source list.
"""

from operator import itemgetter
from typing import Any, Dict, Iterator, List, Literal, Optional

from langchain_core.output_parsers import StrOutputParser
from pydantic import BaseModel, Field

from src.agents.agent import run_agent
from src.core.config import settings
from src.llm import llm_client
from src.memory.conversation import NO_HISTORY, memory
from src.prompts.prompt_templates import RAG_PROMPT, SUMMARIZE_PROMPT, format_context
from src.retrieval.retriever import UserRetriever, retriever, rewrite_question

Mode = Literal["default", "hybrid", "agent", "langchain"]

# The mode recorded with each saved turn ("original" is what the database has always called default)
STORED_MODE = {"default": "original", "hybrid": "hybrid", "langchain": "langchain", "agent": "agent"}

NO_DOCUMENTS = "No documents have been uploaded yet. Please upload some documents first."
NOT_FOUND = "I could not find relevant information in the uploaded documents to answer that question."

SNIPPET_CHARS = 300


# ── Task 2: Structured Output Schema ─────────────────────────────────────────

class RAGResponse(BaseModel):
    """Structured response from the RAG pipeline."""
    answer: str = Field(description="The answer to the user's question based on the document context")
    sources: List[Dict[str, Any]] = Field(default_factory=list, description="Source documents used")
    confidence: float = Field(default=0.0, description="Confidence score from 0.0 to 1.0 based on retrieval similarity")
    tool_used: Optional[str] = Field(default=None, description="Agent mode: which tools answered")


# ── The two retrieval-and-generation strategies ──────────────────────────────

def _retrieve(mode: Mode, user_id: int, query: str) -> List[Dict[str, Any]]:
    """The top chunks for the query, as {"text", "meta", "score"} hits."""
    if mode == "langchain":
        docs = UserRetriever(user_id=user_id, k=settings.top_k).invoke(query)
        return [{"text": d.page_content, "meta": d.metadata, "score": d.metadata["score"]} for d in docs]
    if mode == "hybrid":
        return retriever.search_hybrid(user_id, query, k=settings.top_k)
    return retriever.search(user_id, query, k=settings.top_k)


def _generate(mode: Mode, context: str, question: str, chat_history: str) -> Iterator[str]:
    """Summarize the context, then stream the answer from the summary (Task 3)."""
    llm = llm_client.get_llm()
    if mode == "langchain":
        # Task 15: the whole step as one LCEL chain; the summary feeds the answer prompt
        chain = (
            {
                "context": SUMMARIZE_PROMPT | llm | StrOutputParser(),
                "question": itemgetter("question"),
                "chat_history": itemgetter("chat_history"),
            }
            | RAG_PROMPT
            | llm
            | StrOutputParser()
        )
        return chain.stream({"context": context, "question": question, "chat_history": chat_history})

    summarize_chain = SUMMARIZE_PROMPT | llm | StrOutputParser()
    summary = summarize_chain.invoke({"context": context, "question": question})
    generate_chain = RAG_PROMPT | llm | StrOutputParser()
    return generate_chain.stream({"context": summary, "question": question, "chat_history": chat_history})


def _sources(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One source per (file, page), in retrieval order, with a snippet of the chunk."""
    sources, seen = [], set()
    for r in results:
        src = r["meta"].get("source", "Unknown")
        page = r["meta"].get("page", "?")
        key = f"{src}::{page}"
        if key not in seen:
            seen.add(key)
            snippet = r["text"]
            sources.append({
                "source": src,
                "page": page,
                "snippet": snippet[:SNIPPET_CHARS] + ("…" if len(snippet) > SNIPPET_CHARS else ""),
                "score": round(r["score"], 3),
            })
    return sources


def _refusal(text: str, confidence: float) -> Iterator[Dict[str, Any]]:
    yield {"type": "token", "content": text}
    yield {"type": "done", "sources": [], "confidence": confidence}


# ── The pipeline ──────────────────────────────────────────────────────────────

def events(user_id: int, question: str, session_id: str = "default", mode: Mode = "default",
           save_turn: bool = True) -> Iterator[Dict[str, Any]]:
    """
    Answer a question as a stream of events (see the module docstring).
    save_turn=False is for the agent's document search, whose turn the agent saves itself.
    """
    if mode == "agent":
        yield from _agent_events(user_id, question, session_id)
        return

    # Contextualize the question for search if there's history (Task 4)
    history = memory.format_history(user_id, session_id)
    search_query = rewrite_question(question, history) if history != NO_HISTORY else question

    results = _retrieve(mode, user_id, search_query)
    if not results:
        yield from _refusal(NO_DOCUMENTS, 0.0)
        return

    # Task 2: confidence is the average similarity; Task 7: refuse if even the best is too low
    scores = [r["score"] for r in results]
    confidence = round(sum(scores) / len(scores), 3)
    if max(scores) < settings.confidence_threshold:
        yield from _refusal(NOT_FOUND, confidence)
        return

    answer_text = ""
    for chunk in _generate(mode, format_context(results), question, history):
        answer_text += chunk
        yield {"type": "token", "content": chunk}

    if save_turn:
        memory.add_turn(user_id, session_id, question, answer_text, confidence, mode=STORED_MODE[mode])
    yield {"type": "done", "sources": _sources(results), "confidence": confidence}


def _agent_events(user_id: int, question: str, session_id: str) -> Iterator[Dict[str, Any]]:
    """Run the agent, then send its answer word by word (it has no token stream of its own)."""
    result = run_agent(
        user_id, question, session_id,
        search_documents=lambda query: answer(user_id, query, session_id=session_id, save_turn=False),
    )
    for i, word in enumerate(result["answer"].split(" ")):
        yield {"type": "token", "content": word if i == 0 else " " + word}
    yield {"type": "done", "sources": result["sources"], "confidence": result["confidence"],
           "tool_used": result["tool_used"]}


def answer(user_id: int, question: str, session_id: str = "default", mode: Mode = "default",
           save_turn: bool = True) -> Dict[str, Any]:
    """Run events() to the end and return {"answer", "sources", "confidence", "tool_used"}."""
    tokens: List[str] = []
    done: Dict[str, Any] = {}
    for event in events(user_id, question, session_id, mode, save_turn):
        if event["type"] == "token":
            tokens.append(event["content"])
        elif event["type"] == "done":
            done = event
    return RAGResponse(
        answer="".join(tokens),
        sources=done.get("sources", []),
        confidence=done.get("confidence", 0.0),
        tool_used=done.get("tool_used"),
    ).model_dump()
