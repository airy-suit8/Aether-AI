"""Agent mode: tools are reachable through the API, and the loop is bounded (R11, S4)."""

import time

from fakes import ScriptedChatModel
from langchain_core.messages import AIMessage

from helpers import ask

import agent


def test_agent_uses_the_calculator(client, make_user, fake_llm):
    _, headers = make_user("calc")
    fake_llm.tool_name = "calculator_wrapper"
    fake_llm.tool_input = "max(3, 5)"
    r = ask(client, headers, "What is the larger of 3 and 5?", use_agent=True)
    assert r.status_code == 200, r.text
    assert "max(3, 5) = 5" in r.json()["answer"]
    assert r.json()["tool_used"] == "calculator"


def test_agent_loop_is_bounded(client, make_user, fake_llm, monkeypatch):
    _, headers = make_user("loop")
    # A model that never stops calling tools
    monkeypatch.setattr(ScriptedChatModel, "_reply", lambda self, messages: AIMessage(
        content="", tool_calls=[{"name": "calculator_wrapper", "args": {"expression": "1+1"}, "id": f"c{len(messages)}"}]))
    t0 = time.perf_counter()
    r = ask(client, headers, "Loop forever", use_agent=True)
    assert time.perf_counter() - t0 < 10
    # LangGraph's prebuilt agent stops just before the limit with its own message.
    # Without a limit (default 10,000 steps) this loop would make about 5,000 model calls.
    assert r.status_code == 200, r.text
    assert "need more steps" in r.json()["answer"]
    assert len(fake_llm.prompts) <= agent.AGENT_RECURSION_LIMIT
