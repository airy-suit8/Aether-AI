"""
tests/fakes.py — Offline stand-ins for Gemini, so tests need no API key and make no network calls.

HashingEmbeddings  — bag-of-words vectors: texts that share words get a high cosine similarity,
                     so retrieval behaves meaningfully (unlike random fake embeddings).
FakeOcr            — stands in for the OCR engine: the lines it is given for each page, in turn.
FakeCrossEncoder   — stands in for the reranking model: scores a passage by the question's words
                     it has, and much higher when it has a word the test prefers.
ScriptedChatModel  — answers each pipeline prompt (rewrite, summarize, answer, agent) from the
                     prompt text itself, so an answer can be traced back to the retrieved chunk.
"""

import json
from types import SimpleNamespace
import re
import time
import zlib
from typing import Any, List, Optional

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult


class HashingEmbeddings(Embeddings):
    """Deterministic bag-of-words embedding with a fixed dimension."""

    def __init__(self, size: int = 256):
        self.size = size

    def _embed(self, text: str) -> List[float]:
        vec = [0.0] * self.size
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            vec[zlib.crc32(token.encode()) % self.size] += 1.0
        norm = sum(v * v for v in vec) ** 0.5
        if norm == 0:
            vec[0], norm = 1.0, 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> List[float]:
        return self._embed(text)


class FakeOcr:
    """The OCR engine, offline: for each picture it is shown, the next page of lines it was given
    (none once they run out). Records the shape of each picture."""

    def __init__(self, pages: tuple = ()):
        self.pages = [list(lines) for lines in pages]
        self.pictures: List[tuple] = []

    def __call__(self, picture: Any) -> Any:
        self.pictures.append(picture.shape)
        return SimpleNamespace(txts=tuple(self.pages.pop(0)) if self.pages else ())


class FakeCrossEncoder:
    """The reranker's model, offline. Records each call as (question, passages)."""

    def __init__(self, prefer: tuple = ()):
        self.prefer = {w.lower() for w in prefer}
        self.calls: List[tuple] = []

    def rerank(self, query: str, documents: List[str], **kwargs: Any):
        self.calls.append((query, list(documents)))
        asked = set(re.findall(r"[a-z0-9.]+", query.lower()))
        for doc in documents:
            words = set(re.findall(r"[a-z0-9.]+", doc.lower()))
            yield float(len(asked & words) + 10 * len(self.prefer & words))


AGENT_PROMPT_MARKER = "You can chain multiple tools"


def _between(text: str, start: str, end: str) -> str:
    """Return the text between two markers, or '' if either is missing."""
    i = text.find(start)
    if i < 0:
        return ""
    i += len(start)
    j = text.find(end, i)
    return text[i:j if j >= 0 else None].strip()


class ScriptedChatModel(BaseChatModel):
    """
    A fake chat model that recognises the prompts used by the app.

    delay      — seconds to sleep per call (to simulate a slow model)
    fail_with  — if set, every call raises RuntimeError(fail_with)
    errors     — exceptions raised by the next calls, one per call, before it answers normally
                 (a Gemini quota or availability error, for the retry tests)
    calls      — how many calls were made, failed ones included
    tool_name  — the tool the fake agent calls on its first step
    tool_input — the argument passed to that tool (defaults to the user's question)
    tool_args  — the whole argument dict, for a tool that takes more than one
    judge_reply — what it answers when asked to judge an answer (the evaluation harness)
    citations  — what it adds to an answer written from numbered chunks
    stream_delay — when set, a streamed reply arrives word by word, this many seconds apart
    prompts    — every prompt text received, for assertions

    Every reply reports its usage as Gemini does: usage_metadata, and the model's name in
    response_metadata (on the last piece of a stream), which LangChain's usage counter needs. One
    token per word of the prompt in, one per word of the reply out, so the tests know the counts.
    """

    delay: float = 0.0
    fail_with: Optional[str] = None
    errors: List[Any] = []
    calls: int = 0
    tool_name: str = "document_search_wrapper"
    tool_input: Optional[str] = None
    tool_args: Optional[dict] = None
    judge_reply: str = '{"score": 1.0, "reasoning": "fake judge"}'
    citations: str = "[1]"
    stream_delay: float = 0.0
    prompts: List[str] = []

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        # Tool calls are scripted in _reply, so binding is a no-op.
        return self

    def _generate(self, messages: List[BaseMessage], stop: Optional[List[str]] = None,
                  run_manager: Any = None, **kwargs: Any) -> ChatResult:
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.errors:
            raise self.errors.pop(0)
        if self.fail_with:
            raise RuntimeError(self.fail_with)
        prompt = "\n".join(str(m.content) for m in messages)
        self.prompts.append(prompt)
        message = self._reply(messages)
        used_in, used_out = len(prompt.split()), len(str(message.content).split())
        message.usage_metadata = {"input_tokens": used_in, "output_tokens": used_out, "total_tokens": used_in + used_out}
        message.response_metadata = {"model_name": self._llm_type}
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _stream(self, messages: List[BaseMessage], stop: Optional[List[str]] = None,
                run_manager: Any = None, **kwargs: Any):
        """The reply in one piece, as LangChain streams a model that cannot stream; or, with
        stream_delay, word by word, as a real model streams."""
        message = ScriptedChatModel._generate(self, messages, stop, run_manager, **kwargs).generations[0].message
        if self.stream_delay and not message.tool_calls:
            words = str(message.content).split(" ")
            for i, word in enumerate(words):
                if i:
                    time.sleep(self.stream_delay)
                # The usage and the model's name come once, with the last piece, as Gemini sends them
                last = {"usage_metadata": message.usage_metadata, "response_metadata": message.response_metadata} if i == len(words) - 1 else {}
                yield ChatGenerationChunk(message=AIMessageChunk(content=word if i == 0 else " " + word, **last))
            return
        yield ChatGenerationChunk(message=AIMessageChunk(content=message.content, usage_metadata=message.usage_metadata,
                                                         response_metadata=message.response_metadata, tool_call_chunks=[
            {"name": call["name"], "args": json.dumps(call["args"]), "id": call["id"], "index": i}
            for i, call in enumerate(message.tool_calls)
        ]))

    def _reply(self, messages: List[BaseMessage]) -> AIMessage:
        last = messages[-1]
        text = str(last.content)

        if any(isinstance(m, SystemMessage) and AGENT_PROMPT_MARKER in str(m.content) for m in messages):
            if isinstance(last, ToolMessage):
                return AIMessage(content=f"Agent answer. {last.content}")
            if self.tool_args is not None:
                args = self.tool_args
            elif self.tool_name == "calculator_wrapper":
                args = {"expression": self.tool_input or text}
            elif self.tool_name == "datetime_wrapper":
                args = {}  # its defaults: what is the date and time now
            else:
                args = {"query": self.tool_input or text}
            return AIMessage(content="", tool_calls=[{"name": self.tool_name, "args": args, "id": "call_1"}])

        if "Verdict (JSON):" in text:
            return AIMessage(content=self.judge_reply)
        if "Standalone Question:" in text:
            return AIMessage(content=_between(text, "Current Question:", "Standalone Question:"))
        if "Focused Summary:" in text:
            return AIMessage(content="Summary: " + _between(text, "Document Excerpts:", "\nQuestion:"))
        if "Answer:" in text:
            context = _between(text, "Context:", "\nQuestion:")
            cited = f" {self.citations}" if '<document number="' in context else ""
            return AIMessage(content="Answer from context. " + context[:400] + cited)
        return AIMessage(content="ok")
