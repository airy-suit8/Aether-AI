"""
A model the owner must set up first, through the API: Ollama not running, a model not installed,
a model that cannot use tools, or documents read by another embedding model. Each route that calls
a model says what is wrong in one message, at once and without retrying: a 503 from /chat, an
error event from /chat/stream, a failed upload's status. The errors are raised by fakes.
"""

import httpx
import pytest
from ollama import ResponseError

from fakes import ScriptedChatModel
from src.db import database
from src.embeddings.embedder import ModelSetupError
from src.llm import llm_client
from src.vectordb import vector_store
from helpers import ask, ask_stream, status_of, upload_text, user_id_of

QUESTION = "How often is the Zephyr turbine blade inspection?"
MODES = ["default", "hybrid", "langchain", "agent"]


def ollama_stopped():
    """What a streamed chat raises when nothing listens at Ollama's address."""
    return httpx.ConnectError("[WinError 10061] No connection could be made",
                              request=httpx.Request("POST", "http://127.0.0.1:11434/api/chat"))


class RetryingFake(llm_client.RetryWhenUnavailable, ScriptedChatModel):
    """The fake model, with the retries the real ones have."""


@pytest.fixture
def setup_llm(monkeypatch):
    llm = RetryingFake()
    monkeypatch.setattr(llm_client, "get_llm", lambda **kwargs: llm)
    return llm


@pytest.fixture
def user_with_a_document(client, make_user):
    _, headers = make_user("setup")
    upload_text(client, headers)
    return headers


@pytest.mark.parametrize("mode", MODES)
def test_a_stopped_ollama_is_a_503_that_says_so_and_saves_nothing(client, user_with_a_document, setup_llm, mode):
    setup_llm.errors = [ollama_stopped()]
    r = ask(client, user_with_a_document, QUESTION, session_id="stopped", mode=mode)
    assert r.status_code == 503
    assert r.json()["detail"] == llm_client.OLLAMA_NOT_RUNNING
    assert setup_llm.calls == 1  # not retried: waiting will not start it
    assert database.get_session_turns(user_id_of(user_with_a_document), "stopped") == []


@pytest.mark.parametrize("mode", MODES)
def test_a_missing_model_in_a_stream_is_one_error_event_naming_the_fix(client, user_with_a_document, setup_llm, mode):
    setup_llm.errors = [ResponseError('model "qwen2.5:7b" not found, try pulling it first', 404)]
    status, events = ask_stream(client, user_with_a_document, QUESTION, mode=mode)
    assert status == 200
    assert [e["type"] for e in events] == ["error"]
    assert events[0]["message"] == "The model qwen2.5:7b is not installed in Ollama. Install it with: ollama pull qwen2.5:7b"


def test_agent_mode_with_a_model_that_cannot_use_tools_says_which_modes_still_work(client, user_with_a_document, setup_llm):
    setup_llm.errors = [ResponseError("registry.ollama.ai/library/gemma3:4b does not support tools", 400)]
    r = ask(client, user_with_a_document, QUESTION, mode="agent")
    assert r.status_code == 503
    assert r.json()["detail"].startswith("Agent mode needs a model that can use tools")
    assert "Default or Hybrid mode" in r.json()["detail"]


def test_an_upload_ollama_could_not_embed_fails_with_the_same_message(client, make_user, monkeypatch):
    _, headers = make_user("setupup")

    def stopped(*args, **kwargs):
        raise ConnectionError("Failed to connect to Ollama. Please check that Ollama is downloaded, running and accessible.")

    monkeypatch.setattr(vector_store.store, "add_documents", stopped)
    document = status_of(client, headers, upload_text(client, headers))
    assert document["status"] == "failed"
    assert document["error"] == llm_client.OLLAMA_NOT_RUNNING


def test_documents_read_by_another_embedding_model_are_explained_where_they_are_used(client, user_with_a_document, monkeypatch):
    def changed(*args, **kwargs):
        raise ModelSetupError("The documents here were read with another embedding model. Run python -m src.reembed --apply.")

    monkeypatch.setattr(vector_store.store, "similarity_search", changed)
    r = ask(client, user_with_a_document, QUESTION)
    assert r.status_code == 503
    assert r.json()["detail"].endswith("Run python -m src.reembed --apply.")


def test_an_error_that_is_neither_busy_nor_setup_stays_a_general_error(client, user_with_a_document, setup_llm):
    setup_llm.errors = [httpx.ConnectError("No route to host", request=httpx.Request(
        "POST", "https://generativelanguage.googleapis.com/v1beta/models/m:streamGenerateContent"))]
    r = ask(client, user_with_a_document, QUESTION)
    assert r.status_code == 500 and r.json()["detail"].startswith("Something went wrong on the server.")
