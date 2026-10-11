"""
tests/fakes.py — Offline stand-ins for Gemini, so tests need no API key and make no network calls.

HashingEmbeddings  — bag-of-words vectors: texts that share words get a high cosine similarity,
                     so retrieval behaves meaningfully (unlike random fake embeddings).
ScriptedChatModel  — answers each pipeline prompt (rewrite, summarize, answer, agent) from the
                     prompt text itself, so an answer can be traced back to the retrieved chunk.
"""

import re
import time
import zlib
from typing import Any, List, Optional

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult


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
    tool_name  — the tool the fake agent calls on its first step
    tool_input — the argument passed to that tool (defaults to the user's question)
    prompts    — every prompt text received, for assertions
    """

    delay: float = 0.0
    fail_with: Optional[str] = None
    tool_name: str = "document_search_wrapper"
    tool_input: Optional[str] = None
    prompts: List[str] = []

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        # Tool calls are scripted in _reply, so binding is a no-op.
        return self

    def _generate(self, messages: List[BaseMessage], stop: Optional[List[str]] = None,
                  run_manager: Any = None, **kwargs: Any) -> ChatResult:
        if self.delay:
            time.sleep(self.delay)
        if self.fail_with:
            raise RuntimeError(self.fail_with)
        self.prompts.append("\n".join(str(m.content) for m in messages))
        return ChatResult(generations=[ChatGeneration(message=self._reply(messages))])

    def _reply(self, messages: List[BaseMessage]) -> AIMessage:
        last = messages[-1]
        text = str(last.content)

        if any(isinstance(m, SystemMessage) and AGENT_PROMPT_MARKER in str(m.content) for m in messages):
            if isinstance(last, ToolMessage):
                return AIMessage(content=f"Agent answer. {last.content}")
            return AIMessage(content="", tool_calls=[{
                "name": self.tool_name,
                "args": {"query" if self.tool_name != "calculator_wrapper" else "expression": self.tool_input or text},
                "id": "call_1",
            }])

        if "Standalone Question:" in text:
            return AIMessage(content=_between(text, "Current Question:", "Standalone Question:"))
        if "Focused Summary:" in text:
            return AIMessage(content="Summary: " + _between(text, "Document Excerpts:", "\nQuestion:"))
        if "Answer:" in text:
            return AIMessage(content="Answer from context. " + _between(text, "Context:", "\nQuestion:")[:400])
        return AIMessage(content="ok")
