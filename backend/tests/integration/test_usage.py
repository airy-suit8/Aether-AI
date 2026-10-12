"""What an answer cost (Sprint 8, item 1): each stage's seconds and tokens, with the answer and in
requests.log. The fake model reports one token per word of its prompt and of its reply, so the
counts can be checked exactly; the tokens are never turned into money (decision 7)."""

import json
import uuid

from fakes import AGENT_PROMPT_MARKER
from helpers import ask, ask_stream, upload_text, user_id_of

from src.api.schemas import Usage
from src.core.config import settings
from src.core.logging import request_logger


def _words(prompts):
    return sum(len(p.split()) for p in prompts)


def _names(usage):
    return [stage["name"] for stage in usage["stages"]]


def _assert_totals(usage):
    Usage.model_validate(usage)
    assert usage["input_tokens"] == sum(s["input_tokens"] for s in usage["stages"])
    assert usage["output_tokens"] == sum(s["output_tokens"] for s in usage["stages"])
    assert all(s["seconds"] >= 0 for s in usage["stages"])
    assert usage["seconds"] >= max(s["seconds"] for s in usage["stages"])


def _log_lines():
    for handler in request_logger.handlers:
        handler.flush()
    path = settings.log_dir / "requests.log"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_an_answer_reports_each_stage_with_the_tokens_the_model_reported(client, make_user, fake_llm):
    _, headers = make_user("usage")
    upload_text(client, headers)
    fake_llm.prompts.clear()

    r = ask(client, headers, "How often is the Zephyr turbine blade inspection?")
    assert r.status_code == 200, r.text
    usage = r.json()["usage"]
    _assert_totals(usage)
    assert _names(usage) == ["retrieve", "summarize", "answer"]
    retrieve, summarize, answer = usage["stages"]
    assert retrieve["input_tokens"] == retrieve["output_tokens"] == 0  # a search makes no model call
    assert summarize["output_tokens"] > 0 and answer["output_tokens"] > 0
    assert usage["input_tokens"] == _words(fake_llm.prompts)  # every word of both prompts, once


def test_a_follow_up_adds_the_rewrite_and_a_stream_ends_with_the_same_usage(client, make_user):
    _, headers = make_user("usagestream")
    upload_text(client, headers)
    assert ask(client, headers, "How often is the Zephyr turbine blade inspection?", session_id="u1").status_code == 200

    status, events = ask_stream(client, headers, "Who carries out the inspection?", session_id="u1")
    assert status == 200
    usage = events[-1]["usage"]
    _assert_totals(usage)
    assert _names(usage) == ["rewrite", "retrieve", "summarize", "answer"]


def test_a_refusal_reports_its_search_and_no_tokens(client, make_user):
    _, headers = make_user("usagerefusal")
    r = ask(client, headers, "Anything at all?")  # no documents: refused after the search
    usage = r.json()["usage"]
    _assert_totals(usage)
    assert _names(usage) == ["retrieve"]
    assert usage["input_tokens"] == usage["output_tokens"] == 0


def test_an_agent_answer_counts_its_own_calls_and_each_document_search_once(client, make_user, fake_llm):
    _, headers = make_user("usageagent")
    upload_text(client, headers)
    fake_llm.prompts.clear()

    r = ask(client, headers, "How often is the Zephyr turbine blade inspection?", mode="agent")
    assert r.status_code == 200, r.text
    usage = r.json()["usage"]
    _assert_totals(usage)
    assert _names(usage) == ["agent", "document_search"]
    agent, search = usage["stages"]
    agent_prompts = [p for p in fake_llm.prompts if AGENT_PROMPT_MARKER in p]
    assert len(agent_prompts) == 2  # the call that chose the search, and the one that answered
    assert agent["input_tokens"] == _words(agent_prompts)
    assert search["input_tokens"] == _words(p for p in fake_llm.prompts if AGENT_PROMPT_MARKER not in p) > 0


def test_each_stage_is_written_to_the_request_log_for_both_routes(client, make_user):
    _, headers = make_user("usagelog")
    user_id = user_id_of(headers)
    upload_text(client, headers)
    question = f"How often is the Zephyr turbine blade inspection? {uuid.uuid4().hex}"
    reply = ask(client, headers, question).json()
    status, events = ask_stream(client, headers, question, session_id="s2")
    assert status == 200

    mine = [line for line in _log_lines() if line.get("user_id") == user_id]
    chat = next(line for line in mine if line["event"] == "chat_ok")
    stream = next(line for line in mine if line["event"] == "stream_ok")
    # The stages as the reply had them (the log's own clock for the whole request is "seconds")
    assert chat["usage"]["stages"] == reply["usage"]["stages"]
    assert stream["usage"] == events[-1]["usage"]
    assert stream["mode"] == "default" and stream["sources"] == len(events[-1]["sources"])
    assert question not in (settings.log_dir / "requests.log").read_text(encoding="utf-8")
