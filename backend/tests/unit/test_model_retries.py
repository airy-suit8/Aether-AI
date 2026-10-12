"""
Retries when Gemini is busy (B10, Sprint 5 item 10): a model call that fails for quota (429) or
availability (500, 502, 503, 504) is tried again, up to settings.llm_max_attempts calls, after a
pause that doubles; nothing else is retried, and a stream is not retried once it has started.
The errors are raised by fakes; nothing reaches Google.
"""

import importlib.util

import pytest
from google.genai import errors as genai_errors
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError

from fakes import ScriptedChatModel
from src.core.config import settings
from src.llm import llm_client

PROMPT = "Answer:"


def overloaded():
    return genai_errors.ServerError(503, {"error": {"code": 503, "message": "The model is overloaded.", "status": "UNAVAILABLE"}})


def over_quota():
    """A 429 the way LangChain raises it: its own error, caused by Gemini's."""
    cause = genai_errors.ClientError(429, {"error": {"code": 429, "message": "Quota exceeded.", "status": "RESOURCE_EXHAUSTED"}})
    try:
        raise ChatGoogleGenerativeAIError("Error calling model (RESOURCE_EXHAUSTED)") from cause
    except ChatGoogleGenerativeAIError as e:
        return e


def bad_request():
    return genai_errors.ClientError(400, {"error": {"code": 400, "message": "Invalid argument.", "status": "INVALID_ARGUMENT"}})


class RetryingFake(llm_client.RetryWhenUnavailable, ScriptedChatModel):
    """The fake model with the retries the real one has."""


@pytest.fixture
def pauses(monkeypatch):
    """The pauses between tries, recorded instead of slept."""
    slept = []
    monkeypatch.setattr(llm_client.time, "sleep", slept.append)
    return slept


def test_the_real_model_has_the_retries_and_the_google_client_s_are_off(monkeypatch):
    # A private copy of the module: conftest.py replaces get_llm in the real one with the fake
    spec = importlib.util.find_spec("src.llm.llm_client")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(settings, "google_api_key", "not-a-real-key")  # building the client calls nothing
    llm = module.get_llm()
    assert type(llm).__mro__[1].__name__ == "RetryWhenUnavailable"
    assert llm.max_retries == 1  # one call: the Google client's six retries held a request ~60 s


@pytest.mark.parametrize("error", [overloaded, over_quota], ids=["503", "429 wrapped by LangChain"])
@pytest.mark.parametrize("call", ["invoke", "stream"])
def test_quota_and_availability_errors_are_retried_with_a_doubling_pause(pauses, error, call):
    llm = RetryingFake(errors=[error(), error()])
    reply = llm.invoke(PROMPT).content if call == "invoke" else "".join(c.content for c in llm.stream(PROMPT))
    assert reply.startswith("Answer from context")
    assert llm.calls == 3
    assert pauses == [settings.llm_retry_seconds, settings.llm_retry_seconds * 2] == [2.0, 4.0]


@pytest.mark.parametrize("error", [bad_request, lambda: RuntimeError("bug")], ids=["400", "other"])
def test_other_errors_are_not_retried(pauses, error):
    llm = RetryingFake(errors=[error()])
    with pytest.raises(Exception) as raised:
        llm.invoke(PROMPT)
    assert llm.calls == 1 and pauses == []
    assert not llm_client.is_unavailable(raised.value)


def test_after_the_last_try_the_error_is_passed_on_and_still_reads_as_unavailable(pauses):
    llm = RetryingFake(errors=[overloaded() for _ in range(5)])
    with pytest.raises(genai_errors.ServerError) as raised:
        llm.invoke(PROMPT)
    assert llm.calls == settings.llm_max_attempts == 3
    assert llm_client.is_unavailable(raised.value) and llm_client.unavailable_code(raised.value) == 503


def test_the_number_of_tries_is_a_setting(pauses, monkeypatch):
    monkeypatch.setattr(settings, "llm_max_attempts", 1)
    llm = RetryingFake(errors=[overloaded()])
    with pytest.raises(genai_errors.ServerError):
        llm.invoke(PROMPT)
    assert llm.calls == 1 and pauses == []


class HalfAStream(llm_client.RetryWhenUnavailable, BaseChatModel):
    """Sends one word, then fails as if Gemini went away mid-answer."""
    calls: int = 0

    @property
    def _llm_type(self):
        return "half-a-stream"

    def _generate(self, *args, **kwargs):
        raise NotImplementedError


def test_a_stream_that_has_started_is_not_retried(pauses, monkeypatch):
    def base_stream(self, *args, **kwargs):
        self.calls += 1
        yield ChatGenerationChunk(message=AIMessageChunk(content="Every "))
        raise overloaded()

    monkeypatch.setattr(BaseChatModel, "_stream", base_stream)
    llm = HalfAStream()
    received = []
    with pytest.raises(genai_errors.ServerError):
        for chunk in llm.stream(PROMPT):
            received.append(chunk.content)
    assert received == ["Every "] and llm.calls == 1 and pauses == []
