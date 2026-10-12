"""
Known defects: each test states the correct behaviour and is marked xfail(strict=True) with the
finding id from AUDIT_REPORT.md. The sprint that fixes a defect removes its mark; strict means a
fix that lands without removing the mark fails the suite, so the list stays honest.

To see the real failures:  python -m pytest tests/test_known_defects.py --runxfail

Fixed in Sprint 4 and moved to the ordinary tests: hybrid search (R3, tests/unit/test_search.py)
and parsing (R9, tests/unit/test_parsers.py).
"""

import pytest

from helpers import DOC_TEXT, upload_text, ask, ask_stream
from fakes import ScriptedChatModel
from langchain_core.messages import AIMessage


def known(reason):
    return pytest.mark.xfail(strict=True, reason=reason)


# ── Sources of a refused answer (SPRINT_PLAN.md Status; R5) ───────────────────

REFUSAL = "I could not find relevant information in the uploaded documents."


@pytest.fixture
def refusing_model(monkeypatch):
    """A model that refuses every question, although retrieval passed the threshold."""
    original = ScriptedChatModel._reply

    def reply(self, messages):
        if "Answer:" in str(messages[-1].content) and "Standalone Question:" not in str(messages[-1].content):
            return AIMessage(content=REFUSAL)
        return original(self, messages)

    monkeypatch.setattr(ScriptedChatModel, "_reply", reply)


@known("R5 / Status: a refused answer still lists every retrieved chunk as a source")
@pytest.mark.parametrize("modes", [{}, {"mode": "hybrid"}, {"mode": "langchain"}], ids=["default", "hybrid", "langchain"])
def test_refused_answer_lists_no_sources(client, make_user, refusing_model, modes):
    _, headers = make_user("refuse")
    upload_text(client, headers, text=DOC_TEXT)
    r = ask(client, headers, "How often is the Zephyr turbine blade inspection?", **modes)
    assert r.json()["answer"] == REFUSAL
    assert r.json()["sources"] == []


@known("R5 / Status: a refused streamed answer still lists every retrieved chunk as a source")
def test_refused_streamed_answer_lists_no_sources(client, make_user, refusing_model):
    _, headers = make_user("refuses")
    upload_text(client, headers, text=DOC_TEXT)
    _, events = ask_stream(client, headers, "How often is the Zephyr turbine blade inspection?")
    assert "".join(e["content"] for e in events if e["type"] == "token") == REFUSAL
    assert events[-1]["sources"] == []
