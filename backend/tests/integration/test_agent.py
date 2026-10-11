"""Agent mode: tools are reachable through the API, and the loop is bounded (R11, S4)."""

import time

from fakes import ScriptedChatModel
from langchain_core.messages import AIMessage, ToolMessage

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


def test_agent_uses_the_datetime_tool(client, make_user, fake_llm):
    _, headers = make_user("date")
    fake_llm.tool_name = "datetime_wrapper"
    r = ask(client, headers, "What day is it today?", use_agent=True)
    assert r.status_code == 200, r.text
    assert r.json()["tool_used"] == "datetime"
    assert "Date answer." in r.json()["answer"]
    assert r.json()["sources"] == []


def test_agent_sees_the_earlier_turns_of_the_session(client, make_user, fake_llm):
    _, headers = make_user("agenthist")
    fake_llm.tool_name = "calculator_wrapper"
    fake_llm.tool_input = "2 + 2"
    assert ask(client, headers, "First question about the Halcyon register", session_id="h", use_agent=True).status_code == 200
    fake_llm.prompts.clear()
    assert ask(client, headers, "And the second?", session_id="h", use_agent=True).status_code == 200
    assert "First question about the Halcyon register" in fake_llm.prompts[0]
    assert "Agent answer." in fake_llm.prompts[0]  # the earlier answer is in the history too


def test_empty_final_answer_falls_back_to_the_tool_output(client, make_user, monkeypatch):
    _, headers = make_user("empty")

    def reply(self, messages):
        if isinstance(messages[-1], ToolMessage):
            return AIMessage(content="")  # the model says nothing after the tool
        return AIMessage(content="", tool_calls=[{"name": "calculator_wrapper", "args": {"expression": "6 * 7"}, "id": "c1"}])

    monkeypatch.setattr(ScriptedChatModel, "_reply", reply)
    r = ask(client, headers, "What is six times seven?", use_agent=True)
    assert r.status_code == 200, r.text
    assert r.json()["answer"] == "The result is: 6 * 7 = 42"


def test_empty_answer_without_a_tool_says_so(client, make_user, monkeypatch):
    _, headers = make_user("emptyd")
    monkeypatch.setattr(ScriptedChatModel, "_reply", lambda self, messages: AIMessage(content=""))
    r = ask(client, headers, "Say nothing", use_agent=True)
    assert r.status_code == 200, r.text
    assert r.json()["answer"] == "I executed the tool but encountered an issue formatting the final answer."
    assert r.json()["tool_used"] == "agent_direct"
    assert r.json()["confidence"] == 1.0
