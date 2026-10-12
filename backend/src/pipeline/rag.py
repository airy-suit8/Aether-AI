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
A refusal lists no sources. With settings.answer_from = "chunks" there is no summary step in
any mode: the answer is written from the numbered chunks and its sources are the ones it cites.
"""

import re
import time
from contextlib import contextmanager
from operator import itemgetter
from typing import Any, Dict, Iterator, List, Literal, Optional

from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.output_parsers import StrOutputParser
from pydantic import BaseModel, Field

from src.agents.agent import run_agent
from src.core.config import settings
from src.core.logging import log_event, request_logger
from src.db.database import get_tenant_id
from src.llm import llm_client
from src.memory.conversation import NO_HISTORY, memory
from src.prompts.prompt_templates import (
    CITED_RAG_PROMPT, RAG_PROMPT, SUMMARIZE_PROMPT, format_context, injection_patterns_in,
)
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
    confidence: Optional[float] = Field(
        default=0.0, description="Retrieval similarity, 0.0 to 1.0; None when the agent answered without searching the documents")
    tool_used: Optional[str] = Field(default=None, description="Agent mode: which tools answered")


# ── What one question did (read by the evaluation harness) ───────────────────

class Trace:
    """The chunks retrieved for a question, whether it was refused, and what each stage cost."""

    def __init__(self):
        self.search_query = ""
        self.hits: List[Dict[str, Any]] = []
        self.refused = False
        self.stages: Dict[str, Dict[str, float]] = {}  # name -> seconds, input_tokens, output_tokens

    @contextmanager
    def stage(self, name: str):
        """Time a stage. Yields a LangChain config that counts the tokens of model calls given it."""
        usage = UsageMetadataCallbackHandler()
        start = time.perf_counter()
        try:
            yield {"callbacks": [usage]}
        finally:
            used = list(usage.usage_metadata.values())
            self.stages[name] = {
                "seconds": round(time.perf_counter() - start, 3),
                "input_tokens": sum(u.get("input_tokens", 0) for u in used),
                "output_tokens": sum(u.get("output_tokens", 0) for u in used),
            }


def is_refusal(answer: str) -> bool:
    """True for the pipeline's own refusals and for the model's (rule 2 of RAG_PROMPT)."""
    return answer.strip().startswith(("I could not find relevant information", NO_DOCUMENTS))


# ── The two retrieval-and-generation strategies ──────────────────────────────

def retrieve(mode: Mode, user_id: int, query: str) -> List[Dict[str, Any]]:
    """The user's top chunks for the query, as {"text", "meta", "score"} hits."""
    tenant = get_tenant_id(user_id)  # their chunks' key in the vector store (S2)
    if mode == "langchain":
        docs = UserRetriever(tenant=tenant, k=settings.top_k).invoke(query)
        return [{"text": d.page_content, "meta": d.metadata, "score": d.metadata["score"]} for d in docs]
    if mode == "hybrid":
        return retriever.search_hybrid(tenant, query, k=settings.top_k)
    return retriever.search(tenant, query, k=settings.top_k)


def _generate(mode: Mode, results: List[Dict[str, Any]], question: str, chat_history: str, trace: Trace) -> Iterator[str]:
    """
    Stream the answer. settings.answer_from decides what it is written from: "summary" summarizes
    the chunks and answers from the summary (Task 3); "chunks" answers from the numbered chunks
    in one call, citing them as [1], [2] (R4, R5).
    """
    llm = llm_client.get_llm()
    if settings.answer_from == "chunks":
        with trace.stage("answer") as config:
            yield from (CITED_RAG_PROMPT | llm | StrOutputParser()).stream(
                {"context": format_context(results, numbered=True), "question": question, "chat_history": chat_history},
                config=config)
        return

    context = format_context(results)
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
        with trace.stage("answer") as config:  # one chain, so the summary is counted with the answer
            yield from chain.stream({"context": context, "question": question, "chat_history": chat_history}, config=config)
        return

    with trace.stage("summarize") as config:
        summary = (SUMMARIZE_PROMPT | llm | StrOutputParser()).invoke({"context": context, "question": question}, config=config)
    with trace.stage("answer") as config:
        yield from (RAG_PROMPT | llm | StrOutputParser()).stream(
            {"context": summary, "question": question, "chat_history": chat_history}, config=config)


def _source(r: Dict[str, Any]) -> Dict[str, Any]:
    snippet = r["text"]
    return {
        "source": r["meta"].get("source", "Unknown"),
        "page": r["meta"].get("page", "?"),
        "snippet": snippet[:SNIPPET_CHARS] + ("…" if len(snippet) > SNIPPET_CHARS else ""),
        "score": round(r["score"], 3),
    }


def _sources(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One source per (file, page), in retrieval order, with a snippet of the chunk."""
    sources, seen = [], set()
    for r in results:
        source = _source(r)
        key = f"{source['source']}::{source['page']}"
        if key not in seen:
            seen.add(key)
            sources.append(source)
    return sources


def cited_numbers(answer: str, available: int) -> List[int]:
    """The chunk numbers an answer cites as [n], in order, without repeats or numbers that were not offered."""
    numbers = (int(n) for n in re.findall(r"\[(\d+)\]", answer))
    return sorted({n for n in numbers if 1 <= n <= available})


def _answer_sources(answer: str, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    The sources to show for an answer. None for a refusal: it used no passage (R5). With
    settings.answer_from = "chunks", the chunks the answer cites, each with its "number"; when
    it cites none, every chunk retrieved, since there is no telling which it used.
    """
    if is_refusal(answer):
        return []
    cited = cited_numbers(answer, len(results)) if settings.answer_from == "chunks" else []
    if cited:
        return [{"number": n, **_source(results[n - 1])} for n in cited]
    return _sources(results)


def _report_injection_patterns(user_id: int, results: List[Dict[str, Any]]) -> None:
    """Task 8 as telemetry (S5): log each chunk about to reach the model that reads like an
    instruction. The chunk itself is sent unchanged."""
    for r in results:
        found = injection_patterns_in(r["text"])
        if found:
            log_event(request_logger, "injection_pattern_retrieved", user_id=user_id,
                      source=r["meta"].get("source"), chunk_id=r["meta"].get("chunk_id"), patterns=found)


def _refusal(text: str, confidence: float) -> Iterator[Dict[str, Any]]:
    yield {"type": "token", "content": text}
    yield {"type": "done", "sources": [], "confidence": confidence}


# ── The pipeline ──────────────────────────────────────────────────────────────

def events(user_id: int, question: str, session_id: str = "default", mode: Mode = "default",
           save_turn: bool = True, trace: Optional[Trace] = None) -> Iterator[Dict[str, Any]]:
    """
    Answer a question as a stream of events (see the module docstring).
    save_turn=False is for the agent's document search, whose turn the agent saves itself.
    trace, when given, is filled in as the question runs (the agent mode leaves it empty).
    """
    if mode == "agent":
        yield from _agent_events(user_id, question, session_id)
        return
    trace = trace or Trace()

    # Contextualize the question for search if there's history (Task 4)
    history = memory.format_history(user_id, session_id)
    search_query = question
    if history != NO_HISTORY:
        with trace.stage("rewrite") as config:
            search_query = rewrite_question(question, history, config)
    trace.search_query = search_query

    with trace.stage("retrieve"):
        results = retrieve(mode, user_id, search_query)
    trace.hits = results
    if not results:
        trace.refused = True
        yield from _refusal(NO_DOCUMENTS, 0.0)
        return

    # Task 2: confidence is the average similarity; Task 7: refuse if even the best is too low
    scores = [r["score"] for r in results]
    confidence = round(sum(scores) / len(scores), 3)
    if max(scores) < settings.confidence_threshold:
        trace.refused = True
        yield from _refusal(NOT_FOUND, confidence)
        return
    _report_injection_patterns(user_id, results)

    answer_text = ""
    for chunk in _generate(mode, results, question, history, trace):
        answer_text += chunk
        yield {"type": "token", "content": chunk}
    trace.refused = is_refusal(answer_text)

    sources = _answer_sources(answer_text, results)
    if save_turn:
        memory.add_turn(user_id, session_id, question, answer_text, confidence, mode=STORED_MODE[mode], sources=sources)
    yield {"type": "done", "sources": sources, "confidence": confidence}


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
           save_turn: bool = True, trace: Optional[Trace] = None) -> Dict[str, Any]:
    """Run events() to the end and return {"answer", "sources", "confidence", "tool_used"}."""
    tokens: List[str] = []
    done: Dict[str, Any] = {}
    for event in events(user_id, question, session_id, mode, save_turn, trace):
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
