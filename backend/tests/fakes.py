"""
tests/fakes.py — Offline stand-ins for Gemini, so tests need no API key and make no network calls.

HashingEmbeddings  — bag-of-words vectors: texts that share words get a high cosine similarity,
                     so retrieval behaves meaningfully (unlike random fake embeddings).
ScriptedChatModel  — answers each pipeline prompt (rewrite, summarize, answer, agent) from the
                     prompt text itself, so an answer can be traced back to the retrieved chunk.
"""

import json
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
        self.prompts.append("\n".join(str(m.content) for m in messages))
        return ChatResult(generations=[ChatGeneration(message=self._reply(messages))])

    def _stream(self, messages: List[BaseMessage], stop: Optional[List[str]] = None,
                run_manager: Any = None, **kwargs: Any):
        """The reply in one piece, as LangChain streams a model that cannot stream; or, with
        stream_delay, word by word, as a real model streams."""
        message = ScriptedChatModel._generate(self, messages, stop, run_manager, **kwargs).generations[0].message
        if self.stream_delay and not message.tool_calls:
            for i, word in enumerate(str(message.content).split(" ")):
                if i:
                    time.sleep(self.stream_delay)
                yield ChatGenerationChunk(message=AIMessageChunk(content=word if i == 0 else " " + word))
            return
        yield ChatGenerationChunk(message=AIMessageChunk(content=message.content, tool_call_chunks=[
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
