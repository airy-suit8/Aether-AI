"""Errors are reported as errors, and the agent's tool is visible to the UI (B9, F9)."""

import jwt

import database
from helpers import upload_text, ask, ask_stream

QUESTION = "How often is the Zephyr turbine blade inspection?"


def _user_id(headers):
    token = headers["Authorization"].split()[1]
    return int(jwt.decode(token, options={"verify_signature": False})["sub"])


def test_chat_response_includes_tool_used_in_agent_mode(client, make_user):
    _, headers = make_user("tool")
    upload_text(client, headers)
    r = ask(client, headers, QUESTION, use_agent=True)
    assert r.status_code == 200, r.text
    assert r.json()["tool_used"] == "document_search"


def test_agent_failure_returns_non_200_and_saves_no_turn(client, make_user, fake_llm):
    _, headers = make_user("agentfail")
    upload_text(client, headers)
    fake_llm.fail_with = "model unavailable"
    r = ask(client, headers, QUESTION, session_id="fail", use_agent=True)
    assert r.status_code == 500
    assert database.get_conversation_history(_user_id(headers), "fail") == []


def test_stream_failure_sends_error_event_not_tokens(client, make_user, fake_llm):
    _, headers = make_user("streamfail")
    upload_text(client, headers)
    fake_llm.fail_with = "model unavailable"
    for modes in ({}, {"use_hybrid": True}, {"use_langchain": True}, {"use_agent": True}):
        status, events = ask_stream(client, headers, QUESTION, **modes)
        assert status == 200
        assert [e["type"] for e in events] == ["error"], (modes, events)
        assert events[0]["message"]


def test_stream_done_event_includes_tool_used_in_agent_mode(client, make_user):
    _, headers = make_user("streamtool")
    upload_text(client, headers)
    status, events = ask_stream(client, headers, QUESTION, use_agent=True)
    assert events[-1]["type"] == "done"
    assert events[-1]["tool_used"] == "document_search"
