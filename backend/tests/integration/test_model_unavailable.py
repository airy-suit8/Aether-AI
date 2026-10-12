"""
Gemini busy or over quota, through the API (B10, Sprint 5 item 10): a brief outage is ridden out
by the retries, and a longer one gets one clear message, quickly, in every route that calls a
model: a 503 from /chat, an error event from /chat/stream, a failed upload's status.
"""

import time

import pytest
from google.genai import errors as genai_errors

from fakes import ScriptedChatModel

from src.core.config import settings
from src.db import database
from src.llm import llm_client
from src.vectordb import vector_store
from helpers import ask, ask_stream, status_of, upload_text, user_id_of

QUESTION = "How often is the Zephyr turbine blade inspection?"
MODES = ["default", "hybrid", "langchain", "agent"]


def overloaded():
    return genai_errors.ServerError(503, {"error": {"code": 503, "message": "The model is overloaded.", "status": "UNAVAILABLE"}})


def over_quota():
    return genai_errors.ClientError(429, {"error": {"code": 429, "message": "Quota exceeded.", "status": "RESOURCE_EXHAUSTED"}})


class RetryingFake(llm_client.RetryWhenUnavailable, ScriptedChatModel):
    """The fake model, with the retries the real one has."""


@pytest.fixture
def busy_llm(monkeypatch):
    """The fake model behind the real retries, with no pause between tries."""
    monkeypatch.setattr(settings, "llm_retry_seconds", 0.0)
    llm = RetryingFake()
    monkeypatch.setattr(llm_client, "get_llm", lambda **kwargs: llm)
    return llm


@pytest.fixture
def user_with_a_document(client, make_user):
    _, headers = make_user("busy")
    upload_text(client, headers)
    return headers


@pytest.mark.parametrize("mode", MODES)
def test_a_brief_outage_is_ridden_out(client, user_with_a_document, busy_llm, mode):
    busy_llm.errors = [overloaded(), over_quota()]
    r = ask(client, user_with_a_document, QUESTION, mode=mode)
    assert r.status_code == 200 and "Answer" in r.json()["answer"]


@pytest.mark.parametrize("mode", MODES)
def test_a_long_outage_is_a_503_with_one_clear_message_and_saves_nothing(client, user_with_a_document, busy_llm, mode):
    busy_llm.errors = [overloaded() for _ in range(20)]
    start = time.perf_counter()
    r = ask(client, user_with_a_document, QUESTION, session_id="down", mode=mode)
    assert r.status_code == 503
    assert r.json()["detail"] == llm_client.MODEL_BUSY
    assert time.perf_counter() - start < 2  # was about 60 s, from the Google client's own retries
    assert database.get_session_turns(user_id_of(user_with_a_document), "down") == []


@pytest.mark.parametrize("mode", MODES)
def test_a_long_outage_in_a_stream_is_one_error_event_with_the_same_message(client, user_with_a_document, busy_llm, mode):
    busy_llm.errors = [over_quota() for _ in range(20)]
    status, events = ask_stream(client, user_with_a_document, QUESTION, mode=mode)
    assert status == 200
    assert [e["type"] for e in events] == ["error"]
    assert events[0]["message"] == llm_client.MODEL_BUSY


def test_the_model_is_tried_as_often_as_the_setting_says(client, user_with_a_document, busy_llm):
    busy_llm.errors = [overloaded() for _ in range(20)]
    ask(client, user_with_a_document, QUESTION)
    assert busy_llm.calls == settings.llm_max_attempts == 3


def test_a_bad_request_is_not_retried_and_stays_a_general_error(client, user_with_a_document, busy_llm):
    busy_llm.errors = [genai_errors.ClientError(400, {"error": {"code": 400, "message": "Bad.", "status": "INVALID_ARGUMENT"}})]
    r = ask(client, user_with_a_document, QUESTION)
    assert r.status_code == 500 and r.json()["detail"].startswith("Something went wrong on the server.")
    assert busy_llm.calls == 1


def test_an_upload_the_embedding_service_could_not_take_fails_with_the_clear_message(client, make_user, monkeypatch):
    _, headers = make_user("busyup")

    def over_quota_store(*args, **kwargs):
        raise over_quota()

    monkeypatch.setattr(vector_store.store, "add_documents", over_quota_store)
    document = status_of(client, headers, upload_text(client, headers))
    assert document["status"] == "failed"
    assert document["error"] == ("The AI service was busy or over its usage limit while reading this file. "
                                 "Please upload it again in a minute.")
