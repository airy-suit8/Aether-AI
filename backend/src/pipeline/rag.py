"""
pipeline/rag.py — the one question-answering pipeline.

events() yields what the client sees, in order:
  {"type": "token", "content": str}                      zero or more pieces of the answer
  {"type": "done", "sources": [...], "confidence": float, "turn_id": int | None, "usage": {...}}
                                                         last; agent answers add "tool_used" and "steps"
turn_id names the saved turn, for feedback (F10); None when no turn was saved (a refusal, or the
agent's own document search). A turn is saved only after its last token: a stream the client
closes early (Stop) is not run to the end, so it saves no turn.
The streaming route sends each event as it comes; answer() collects them for the plain route.
usage is what the answer cost (Sprint 8, item 1): its seconds and the tokens the model's API
reported, in all and for each stage in the order it ran (see _usage).
Errors are raised, not yielded: each route reports them in its own way.

One pipeline, four modes:
  default    rewrite a follow-up -> dense search -> summarize -> answer (Task 3, LCEL)
  hybrid     the same, with hybrid (dense + BM25) search
  langchain  Tasks 14-15: retrieval through a LangChain retriever object (UserRetriever), and
             summarize -> answer composed as one LCEL chain (RetrievalQA style)
  agent      the tool-calling agent (Task 11); its document search runs this pipeline in
             default mode without saving a turn
Every mode shares the prompts, the memory, the confidence threshold and the source list.
A refusal lists no sources. With settings.answer_from = "chunks" (the default) there is no
summary step in any mode: the answer is written from the numbered chunks and its sources are the
ones it cites.

Every mode also shares the scope (retrieval/scope.py): the documents a question searches, chosen
in the request or named in the question, and said in the done event ("scope"). What is searched
is then widened where a question needs it: each document's own best passages for a question
about several at once, each document's first passage for a question about its title or authors,
and the passages either side of the best hits (settings.chunk_window). The added passages are
context: they do not count towards the confidence.
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
from src.retrieval import scope as scoping
from src.retrieval.retriever import UserRetriever, retriever, rewrite_question
from src.retrieval.scope import Scope
from src.vectordb.vector_store import store

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
    turn_id: Optional[int] = Field(default=None, description="The saved turn, for feedback; None when none was saved")
    usage: Optional[Dict[str, Any]] = Field(default=None, description="Seconds and tokens, in all and by stage")
    steps: Optional[List[Dict[str, str]]] = Field(default=None, description="Agent mode: each tool call, in order")
    scope: Optional[Dict[str, Any]] = Field(default=None, description="The documents searched, and how they were picked")


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


def _usage(trace: Trace, started: float, more: List[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """
    What an answer cost (Sprint 8, item 1): the seconds from the question to the answer, and the
    tokens the model's API reported, in all and for each stage in the order it ran (more: stages
    the trace does not hold, such as the agent's document searches). Tokens are not turned into
    money: prices change, and the app does not know the account's tier (decision 7).
    """
    stages = [{"name": name, **stage} for name, stage in trace.stages.items()] + list(more)
    return {
        "seconds": round(time.perf_counter() - started, 3),
        "input_tokens": sum(stage["input_tokens"] for stage in stages),
        "output_tokens": sum(stage["output_tokens"] for stage in stages),
        "stages": stages,
    }


def is_refusal(answer: str) -> bool:
    """True for the pipeline's own refusals and for the model's (rule 2 of RAG_PROMPT)."""
    return answer.strip().startswith(("I could not find relevant information", NO_DOCUMENTS))


# ── The two retrieval-and-generation strategies ──────────────────────────────

def _search(mode: Mode, tenant: str, query: str, k: int, document_ids: Optional[List[int]]) -> List[Dict[str, Any]]:
    """One search of the mode's kind, as {"text", "meta", "score"} hits."""
    if mode == "langchain":
        docs = UserRetriever(tenant=tenant, k=k, document_ids=document_ids).invoke(query)
        return [{"text": d.page_content, "meta": d.metadata, "score": d.metadata["score"]} for d in docs]
    if mode == "hybrid":
        return retriever.search_hybrid(tenant, query, k=k, document_ids=document_ids)
    return retriever.search(tenant, query, k=k, document_ids=document_ids)


def _key(hit: Dict[str, Any]) -> str:
    return hit["meta"].get("chunk_id") or hit["text"]


def _added(tenant: str, query: str, passages: List[tuple], hits: List[Dict[str, Any]], why: str) -> List[Dict[str, Any]]:
    """Passages (text, meta) not among the hits yet, as hits marked added, scored against the query."""
    have = {_key(h) for h in hits}
    new, seen = [], set()
    for text, meta in passages:
        key = meta.get("chunk_id") or text
        if key not in have and key not in seen:
            seen.add(key)
            new.append((text, meta))
    scores = store.similarities(tenant, query, [m["chunk_id"] for _, m in new if m.get("chunk_id")]) if new else {}
    return [{"text": text, "meta": meta, "score": scores.get(meta.get("chunk_id"), 0.0), "added": why} for text, meta in new]


def _document_of(hit: Dict[str, Any]) -> str:
    return str(hit["meta"].get("document_id", hit["meta"].get("source")))


def _in_reading_order(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Each document's passages together, in the order they come in it; documents in the order of
    their best passage. A model follows a paper better as it runs (Verba orders its context so)."""
    best: Dict[str, float] = {}
    for h in hits:
        best[_document_of(h)] = max(best.get(_document_of(h), 0.0), h["score"])
    return sorted(hits, key=lambda h: (-best[_document_of(h)], _document_of(h), h["meta"].get("chunk_index", 0)))


def retrieve(mode: Mode, user_id: int, query: str, scope: Optional[Scope] = None) -> List[Dict[str, Any]]:
    """
    The user's top chunks for the query, as {"text", "meta", "score"} hits, within the scope.
    A question about several documents at once gets the best passages of each; one about a
    document's title or authors also gets each document's first passage; the best two hits come
    with the passages either side of them. Added passages carry "added" and are context only.
    """
    tenant = get_tenant_id(user_id)  # their chunks' key in the vector store (S2)
    documents = scope.documents if scope else []
    if scope and scope.each and 1 < len(documents) <= scoping.MAX_EACH:
        per = max(2, -(-settings.top_k // len(documents)))
        hits = [hit for doc in documents for hit in _search(mode, tenant, query, per, [doc.id])]
    else:
        hits = _search(mode, tenant, query, settings.top_k, scope.ids if scope else None)
    if not hits:
        return []
    if scope and scope.front_matter and len(documents) <= scoping.MAX_EACH:
        first = store.first_passages(tenant)
        hits += _added(tenant, query, [first[d.id] for d in documents if d.id in first], hits, "start")
    if settings.chunk_window:
        around: List[tuple] = []
        for hit in sorted((h for h in hits if "added" not in h), key=lambda h: -h["score"])[:2]:
            meta = hit["meta"]
            if meta.get("document_id") is not None and meta.get("chunk_index") is not None:
                around += store.passages_around(tenant, meta["document_id"], meta["chunk_index"], settings.chunk_window)
        hits += _added(tenant, query, around, hits, "neighbour")
    return _in_reading_order(hits)


def _generate(mode: Mode, results: List[Dict[str, Any]], question: str, chat_history: str, trace: Trace,
              titles: Optional[Dict[int, str]] = None) -> Iterator[str]:
    """
    Stream the answer. settings.answer_from decides what it is written from: "summary" summarizes
    the chunks and answers from the summary (Task 3); "chunks" answers from the numbered chunks
    in one call, citing them as [1], [2] (R4, R5).
    """
    llm = llm_client.get_llm()
    if settings.answer_from == "chunks":
        with trace.stage("answer") as config:
            yield from (CITED_RAG_PROMPT | llm | StrOutputParser()).stream(
                {"context": format_context(results, numbered=True, titles=titles), "question": question,
                 "chat_history": chat_history},
                config=config)
        return

    context = format_context(results, titles=titles)
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
    snippet, meta = r["text"], r["meta"]
    source = {
        "source": meta.get("source", "Unknown"),
        "page": meta.get("page", "?"),
        "snippet": snippet[:SNIPPET_CHARS] + ("…" if len(snippet) > SNIPPET_CHARS else ""),
        "score": round(r["score"], 3),
    }
    # Which document, of what kind, and where the passage sits in it: files without pages
    # (Word, text) are located by passage
    for name, key in (("document_id", "document_id"), ("kind", "type"), ("passage", "chunk_index"), ("passages", "total_chunks")):
        if meta.get(key) is not None:
            source[name] = meta[key]
    return source


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


def _refusal(text: str, confidence: float, usage: Dict[str, Any], scope: Optional[Scope] = None) -> Iterator[Dict[str, Any]]:
    yield {"type": "token", "content": text}
    yield {"type": "done", "sources": [], "confidence": confidence, "turn_id": None, "usage": usage,
           "scope": scope.described() if scope else None}


# ── The pipeline ──────────────────────────────────────────────────────────────

def events(user_id: int, question: str, session_id: str = "default", mode: Mode = "default",
           save_turn: bool = True, trace: Optional[Trace] = None,
           document_ids: Optional[List[int]] = None) -> Iterator[Dict[str, Any]]:
    """
    Answer a question as a stream of events (see the module docstring).
    save_turn=False is for the agent's document search, whose turn the agent saves itself.
    trace, when given, is filled in as the question runs (in agent mode, with one "agent" stage).
    document_ids: the documents the request chose to search in; None leaves it to the question.
    """
    started = time.perf_counter()
    trace = trace or Trace()
    if mode == "agent":
        scope = scoping.resolve(user_id, question, document_ids)
        yield from _agent_events(user_id, question, session_id, trace, started, scope)
        return

    # Contextualize the question for search if there's history (Task 4)
    history = memory.format_history(user_id, session_id)
    search_query = question
    if history != NO_HISTORY:
        with trace.stage("rewrite") as config:
            search_query = rewrite_question(question, history, config)
    trace.search_query = search_query

    with trace.stage("retrieve"):
        scope = scoping.resolve(user_id, question, document_ids, also=search_query if search_query != question else "")
        results = retrieve(mode, user_id, search_query, scope)
    trace.hits = results
    if not results:
        trace.refused = True
        yield from _refusal(NO_DOCUMENTS, 0.0, _usage(trace, started), scope)
        return

    # Task 2: confidence is the average similarity of the passages found (not of those added as
    # context); Task 7: refuse if even the best is too low
    scores = [r["score"] for r in results if "added" not in r]
    confidence = round(sum(scores) / len(scores), 3)
    if max(scores) < settings.confidence_threshold:
        trace.refused = True
        yield from _refusal(NOT_FOUND, confidence, _usage(trace, started), scope)
        return
    _report_injection_patterns(user_id, results)

    titles = {d.id: d.title for d in scope.all_documents if d.title}
    answer_text = ""
    for chunk in _generate(mode, results, question, history, trace, titles):
        answer_text += chunk
        yield {"type": "token", "content": chunk}
    trace.refused = is_refusal(answer_text)

    sources = _answer_sources(answer_text, results)
    turn_id = None
    if save_turn:
        turn_id = memory.add_turn(user_id, session_id, question, answer_text, confidence, mode=STORED_MODE[mode],
                                  sources=sources)
    yield {"type": "done", "sources": sources, "confidence": confidence, "turn_id": turn_id,
           "usage": _usage(trace, started), "scope": scope.described()}


def _agent_events(user_id: int, question: str, session_id: str, trace: Trace, started: float,
                  scope: Scope) -> Iterator[Dict[str, Any]]:
    """Run the agent, then send its answer word by word (it has no token stream of its own).
    The turn is saved after the last word, as in the other modes: a stream closed before then
    saves none (Sprint 6, decision 11).
    Its usage has an "agent" stage, the agent's own model calls, and a "document_search" stage
    for each search it made, whose seconds the agent's stage does not count again."""
    searches: List[Dict[str, Any]] = []

    def search_documents(query: str) -> Dict[str, Any]:
        found = answer(user_id, query, session_id=session_id, save_turn=False, document_ids=scope.ids)
        searches.append({"name": "document_search", **{k: found["usage"][k] for k in ("seconds", "input_tokens", "output_tokens")}})
        return found

    with trace.stage("agent") as config:
        result = run_agent(user_id, question, session_id, search_documents=search_documents, config=config)
    agent = trace.stages["agent"]
    agent["seconds"] = round(max(0.0, agent["seconds"] - sum(s["seconds"] for s in searches)), 3)
    for i, word in enumerate(result["answer"].split(" ")):
        yield {"type": "token", "content": word if i == 0 else " " + word}
    # The database column is a number, so an answer that searched no document records 0
    turn_id = memory.add_turn(user_id, session_id, question, result["answer"], result["confidence"] or 0.0,
                              mode=STORED_MODE["agent"], sources=result["sources"], tool_used=result["tool_used"])
    yield {"type": "done", "sources": result["sources"], "confidence": result["confidence"],
           "tool_used": result["tool_used"], "steps": result["steps"], "turn_id": turn_id,
           "usage": _usage(trace, started, searches), "scope": scope.described()}


def answer(user_id: int, question: str, session_id: str = "default", mode: Mode = "default",
           save_turn: bool = True, trace: Optional[Trace] = None,
           document_ids: Optional[List[int]] = None) -> Dict[str, Any]:
    """Run events() to the end and return {"answer", "sources", "confidence", "tool_used", "steps",
    "turn_id", "usage", "scope"}."""
    tokens: List[str] = []
    done: Dict[str, Any] = {}
    for event in events(user_id, question, session_id, mode, save_turn, trace, document_ids):
        if event["type"] == "token":
            tokens.append(event["content"])
        elif event["type"] == "done":
            done = event
    return RAGResponse(
        answer="".join(tokens),
        sources=done.get("sources", []),
        confidence=done.get("confidence", 0.0),
        tool_used=done.get("tool_used"),
        steps=done.get("steps"),
        turn_id=done.get("turn_id"),
        usage=done.get("usage"),
        scope=done.get("scope"),
    ).model_dump()
