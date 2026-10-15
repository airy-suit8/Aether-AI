"""
Any service that speaks OpenAI's API (llm_provider / embedding_provider "openai"): the settings
that choose it, the factories that build its models, and what the person asking is told when the
service is out of reach, refuses the key, lacks the model, or cannot use tools. Nothing here asks
a model anything: building a client makes no request, and the one connection made is to a closed
port on this computer.
"""

import importlib.util

import httpx
import openai
import pytest

from fakes import ScriptedChatModel
from src.core.config import Settings, settings
from src.embeddings.embedder import ModelSetupError
from src.llm import llm_client

CLOSED_PORT = "http://127.0.0.1:9/v1"  # nothing listens there: a server that is not running


def fresh(module_name):
    """A private copy of a module, unaffected by the fakes conftest.py installs in the real one."""
    spec = importlib.util.find_spec(module_name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def settings_of(monkeypatch, **values):
    for name in ("AETHER_LLM_PROVIDER", "AETHER_EMBEDDING_PROVIDER", "AETHER_LLM_MODEL", "AETHER_EMBEDDING_MODEL"):
        monkeypatch.delenv(name, raising=False)
    return Settings(_env_file=None, **values)


@pytest.fixture
def service(monkeypatch):
    """Both models from an OpenAI-compatible service at a closed port, with no key."""
    for name, value in {"llm_provider": "openai", "embedding_provider": "openai", "llm_model": "local-chat",
                        "embedding_model": "local-embed", "openai_url": CLOSED_PORT, "openai_api_key": "",
                        "openai_reasoning_effort": ""}.items():
        monkeypatch.setattr(settings, name, value)


def response(status: int, url: str = "http://127.0.0.1:1234/v1/chat/completions") -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("POST", url))


def status_error(cls, status: int, message: str):
    return cls(message, response=response(status), body=None)


def wrapped(error: BaseException) -> BaseException:
    try:
        raise RuntimeError("Error calling the model") from error
    except RuntimeError as outer:
        return outer


# ── Settings ──────────────────────────────────────────────────────────────────

def test_an_openai_compatible_service_has_no_default_models(monkeypatch):
    s = settings_of(monkeypatch, llm_provider="openai", embedding_provider="openai")
    assert (s.llm_model, s.embedding_model) == ("", "")
    assert s.openai_url == "https://api.openai.com/v1"


def test_named_models_are_kept_and_label_the_store(monkeypatch):
    s = settings_of(monkeypatch, embedding_provider="openai", embedding_model="text-embedding-3-small",
                    llm_provider="openai", llm_model="llama-3.3-70b-versatile")
    assert s.llm_model == "llama-3.3-70b-versatile"
    assert s.embedding_label() == "openai:text-embedding-3-small"


def test_its_key_has_its_usual_name(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert Settings(_env_file=None).openai_api_key == "sk-test"


# ── Factories ─────────────────────────────────────────────────────────────────

def test_the_chat_model_has_the_app_s_limits_and_retries_and_needs_no_key(service):
    module = fresh("src.llm.llm_client")
    llm = module.get_llm()
    assert isinstance(llm, module.OpenAICompatibleChat)
    assert (llm.model_name, llm.openai_api_base) == ("local-chat", CLOSED_PORT)
    assert llm.openai_api_key.get_secret_value() == "none"  # the client needs one; a local server takes any
    assert llm.temperature == settings.llm_temperature
    assert llm.request_timeout == settings.llm_timeout_seconds
    assert llm.max_tokens == settings.llm_max_output_tokens
    assert llm.max_retries == 0 and llm.stream_usage is True
    assert llm.reasoning_effort is None  # not sent: OpenAI's other models refuse it


def test_a_key_and_a_reasoning_effort_are_passed_on_when_set(service, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(settings, "openai_reasoning_effort", "none")
    llm = fresh("src.llm.llm_client").get_llm(temperature=0.0, model="judge-model")
    assert llm.openai_api_key.get_secret_value() == "sk-test"
    assert (llm.reasoning_effort, llm.temperature, llm.model_name) == ("none", 0.0, "judge-model")


def test_the_embeddings_send_the_texts_as_they_are(service):
    embeddings = fresh("src.embeddings.embedder").get_embeddings()
    assert type(embeddings).__name__ == "OpenAIEmbeddings"
    assert (embeddings.model, embeddings.openai_api_base) == ("local-embed", CLOSED_PORT)
    assert embeddings.check_embedding_ctx_length is False  # no tiktoken: the service has its own tokenizer
    assert embeddings.max_retries == 0
    assert embeddings.request_timeout == settings.embedding_timeout_seconds


@pytest.mark.parametrize("field, setting, module_name, factory", [
    ("llm_model", "AETHER_LLM_MODEL", "src.llm.llm_client", "get_llm"),
    ("embedding_model", "AETHER_EMBEDDING_MODEL", "src.embeddings.embedder", "get_embeddings"),
])
def test_a_model_not_named_says_which_setting_to_set(service, monkeypatch, field, setting, module_name, factory):
    monkeypatch.setattr(settings, field, "")
    # A private copy of the module has its own copy of ModelSetupError: matched by name
    with pytest.raises(RuntimeError) as missing:
        getattr(fresh(module_name), factory)()
    assert type(missing.value).__name__ == ModelSetupError.__name__
    assert setting in str(missing.value) and CLOSED_PORT in str(missing.value)


# ── What the person asking is told ────────────────────────────────────────────

def test_a_service_out_of_reach_is_named_and_not_retried(service):
    with pytest.raises(openai.APIConnectionError) as out_of_reach:
        fresh("src.llm.llm_client").get_llm().invoke("Hello")
    said = llm_client.setup_problem(out_of_reach.value)
    assert said.startswith(f"The AI service at {CLOSED_PORT} could not be reached")
    assert not llm_client.is_unavailable(out_of_reach.value)


@pytest.mark.parametrize("error, said", [
    (status_error(openai.AuthenticationError, 401, "Incorrect API key provided"), "refused the key. Set OPENAI_API_KEY"),
    (status_error(openai.PermissionDeniedError, 403, "Forbidden"), "refused the key"),
    (status_error(openai.NotFoundError, 404, 'model "local-chat" not found'), "has no model local-chat. Set AETHER_LLM_MODEL"),
    (status_error(openai.BadRequestError, 400, "local-chat does not support tools"), "Agent mode needs a model that can use tools"),
])
def test_what_the_owner_must_fix_is_said_plainly(service, error, said):
    assert said in llm_client.setup_problem(wrapped(error))
    assert not llm_client.is_unavailable(wrapped(error))


def test_a_reasoning_effort_the_model_refuses_says_to_remove_it(service, monkeypatch):
    refused = status_error(openai.BadRequestError, 400, "Unrecognized request argument supplied: reasoning_effort")
    assert llm_client.setup_problem(refused) is None  # not set: some other bad request
    monkeypatch.setattr(settings, "openai_reasoning_effort", "none")
    assert "Remove it from backend/.env" in llm_client.setup_problem(refused)


def test_a_timeout_and_other_bad_requests_are_not_setup_problems(service):
    assert llm_client.setup_problem(openai.APITimeoutError(request=httpx.Request("POST", CLOSED_PORT))) is None
    assert llm_client.setup_problem(status_error(openai.BadRequestError, 400, "context length exceeded")) is None


@pytest.mark.parametrize("cls, status", [(openai.RateLimitError, 429), (openai.InternalServerError, 503)])
def test_a_busy_service_is_busy_not_broken_and_is_tried_again(service, monkeypatch, cls, status):
    busy = status_error(cls, status, "slow down")
    assert llm_client.is_unavailable(wrapped(busy)) and llm_client.setup_problem(busy) is None

    class RetryingFake(llm_client.RetryWhenUnavailable, ScriptedChatModel):
        """The fake model, with the retries the real ones have."""

    monkeypatch.setattr(settings, "llm_retry_seconds", 0.0)
    llm = RetryingFake(errors=[busy])
    llm.invoke("Answer:")
    assert llm.calls == 2
