"""Agent mode: tools are reachable through the API, and the loop is bounded (R11, S4)."""

import time
from datetime import datetime

from fakes import ScriptedChatModel
from langchain_core.messages import AIMessage, ToolMessage

from helpers import ask, ask_stream, upload_text

from src.core.config import settings


def test_agent_uses_the_calculator(client, make_user, fake_llm):
    _, headers = make_user("calc")
    fake_llm.tool_name = "calculator_wrapper"
    fake_llm.tool_input = "max(3, 5)"
    r = ask(client, headers, "What is the larger of 3 and 5?", mode="agent")
    assert r.status_code == 200, r.text
    assert "max(3, 5) = 5" in r.json()["answer"]
    assert r.json()["tool_used"] == "calculator"


def test_agent_loop_is_bounded(client, make_user, fake_llm, monkeypatch):
    _, headers = make_user("loop")
    # A model that never stops calling tools
    monkeypatch.setattr(ScriptedChatModel, "_reply", lambda self, messages: AIMessage(
        content="", tool_calls=[{"name": "calculator_wrapper", "args": {"expression": "1+1"}, "id": f"c{len(messages)}"}]))
    t0 = time.perf_counter()
    r = ask(client, headers, "Loop forever", mode="agent")
    assert time.perf_counter() - t0 < 10
    # LangGraph's prebuilt agent stops just before the limit with its own message.
    # Without a limit (default 10,000 steps) this loop would make about 5,000 model calls.
    assert r.status_code == 200, r.text
    assert "need more steps" in r.json()["answer"]
    assert len(fake_llm.prompts) <= settings.agent_recursion_limit


def test_agent_uses_the_datetime_tool(client, make_user, fake_llm):
    _, headers = make_user("date")
    fake_llm.tool_name = "datetime_wrapper"
    r = ask(client, headers, "What day is it today?", mode="agent")
    assert r.status_code == 200, r.text
    assert r.json()["tool_used"] == "datetime"
    assert f"Today is {datetime.now():%A}, {datetime.now().day} {datetime.now():%B %Y}." in r.json()["answer"]
    assert r.json()["sources"] == []
    # R11: the date comes from Python. The model was asked twice, to pick the tool and to answer,
    # and never to work out a date
    assert len(fake_llm.prompts) == 2


def test_agent_counts_days_with_the_tool_arguments_it_chooses(client, make_user, fake_llm):
    _, headers = make_user("days")
    fake_llm.tool_name = "datetime_wrapper"
    fake_llm.tool_args = {"operation": "days_between", "start": "2026-01-01", "end": "2026-03-01"}
    r = ask(client, headers, "How many days from New Year to the first of March 2026?", mode="agent")
    assert "From 2026-01-01 to 2026-03-01 is 59 days." in r.json()["answer"]


def test_an_answer_that_searched_no_document_has_no_confidence(client, make_user, fake_llm):
    # R11: such an answer used to come back with confidence 1.0
    _, headers = make_user("noconf")
    fake_llm.tool_name = "calculator_wrapper"
    fake_llm.tool_input = "6 * 7"
    r = ask(client, headers, "What is six times seven?", session_id="calc", mode="agent")
    assert r.json()["tool_used"] == "calculator" and r.json()["sources"] == []
    assert r.json()["confidence"] is None
    _, events = ask_stream(client, headers, "And again?", session_id="calc", mode="agent")
    assert events[-1]["confidence"] is None


def test_an_answer_from_a_document_search_keeps_that_search_s_confidence(client, make_user):
    _, headers = make_user("conf")
    upload_text(client, headers)
    r = ask(client, headers, "How often is the Zephyr turbine blade inspection?", mode="agent")
    assert r.json()["tool_used"] == "document_search"
    assert 0.3 <= r.json()["confidence"] <= 1.0 and r.json()["sources"]


def test_agent_sees_the_earlier_turns_of_the_session(client, make_user, fake_llm):
    _, headers = make_user("agenthist")
    fake_llm.tool_name = "calculator_wrapper"
    fake_llm.tool_input = "2 + 2"
    assert ask(client, headers, "First question about the Halcyon register", session_id="h", mode="agent").status_code == 200
    fake_llm.prompts.clear()
    assert ask(client, headers, "And the second?", session_id="h", mode="agent").status_code == 200
    assert "First question about the Halcyon register" in fake_llm.prompts[0]
    assert "Agent answer." in fake_llm.prompts[0]  # the earlier answer is in the history too


def test_empty_final_answer_falls_back_to_the_tool_output(client, make_user, monkeypatch):
    _, headers = make_user("empty")

    def reply(self, messages):
        if isinstance(messages[-1], ToolMessage):
            return AIMessage(content="")  # the model says nothing after the tool
        return AIMessage(content="", tool_calls=[{"name": "calculator_wrapper", "args": {"expression": "6 * 7"}, "id": "c1"}])

    monkeypatch.setattr(ScriptedChatModel, "_reply", reply)
    r = ask(client, headers, "What is six times seven?", mode="agent")
    assert r.status_code == 200, r.text
    assert r.json()["answer"] == "The result is: 6 * 7 = 42"


def test_empty_answer_without_a_tool_says_so(client, make_user, monkeypatch):
    _, headers = make_user("emptyd")
    monkeypatch.setattr(ScriptedChatModel, "_reply", lambda self, messages: AIMessage(content=""))
    r = ask(client, headers, "Say nothing", mode="agent")
    assert r.status_code == 200, r.text
    assert r.json()["answer"] == "I executed the tool but encountered an issue formatting the final answer."
    assert r.json()["tool_used"] == "agent_direct"
    assert r.json()["confidence"] is None  # R11: was 1.0
