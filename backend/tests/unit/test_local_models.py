"""
Models on this computer through Ollama: the settings that choose them, the factories that build
them, and what the person asking is told when Ollama is not running or a model is missing.
Nothing here asks a model anything: building a client makes no request, and the one connection
made is to a closed port on this computer, which is how a stopped Ollama looks.
"""

import importlib.util

import httpx
import pytest
from ollama import ResponseError

from fakes import ScriptedChatModel
from src.core.config import OLLAMA_EMBEDDING_MODEL, OLLAMA_LLM_MODEL, Settings, settings
from src.embeddings.embedder import ModelSetupError
from src.llm import llm_client

CLOSED_PORT = "http://127.0.0.1:9"  # nothing listens there: a stopped Ollama


def fresh(module_name):
    """A private copy of a module, unaffected by the fakes conftest.py installs in the real one."""
    spec = importlib.util.find_spec(module_name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def settings_of(monkeypatch, **values):
    """Settings from these values alone: no backend/.env and no AETHER_ variables for the models."""
    for name in ("AETHER_LLM_PROVIDER", "AETHER_EMBEDDING_PROVIDER", "AETHER_LLM_MODEL", "AETHER_EMBEDDING_MODEL"):
        monkeypatch.delenv(name, raising=False)
    return Settings(_env_file=None, **values)


@pytest.fixture
def ollama(monkeypatch):
    """Both models from Ollama, at an address where nothing listens, and no Gemini key."""
    for name, value in {"llm_provider": "ollama", "embedding_provider": "ollama", "llm_model": OLLAMA_LLM_MODEL,
                        "embedding_model": OLLAMA_EMBEDDING_MODEL, "ollama_url": CLOSED_PORT, "google_api_key": ""}.items():
        monkeypatch.setattr(settings, name, value)


# ── Settings ──────────────────────────────────────────────────────────────────

def test_gemini_stays_the_default(monkeypatch):
    s = settings_of(monkeypatch)
    assert (s.llm_provider, s.embedding_provider) == ("gemini", "gemini")
    assert s.llm_model == Settings.model_fields["llm_model"].default
    assert s.embedding_label() == "gemini:" + Settings.model_fields["embedding_model"].default


def test_ollama_brings_its_own_default_models(monkeypatch):
    s = settings_of(monkeypatch, llm_provider="ollama", embedding_provider="ollama")
    assert (s.llm_model, s.embedding_model) == (OLLAMA_LLM_MODEL, OLLAMA_EMBEDDING_MODEL)
    assert s.embedding_label() == f"ollama:{OLLAMA_EMBEDDING_MODEL}"


def test_each_provider_is_chosen_on_its_own_and_a_named_model_is_kept(monkeypatch):
    s = settings_of(monkeypatch, llm_provider="ollama", llm_model="gemma3:4b")
    assert s.llm_model == "gemma3:4b"
    assert (s.embedding_provider, s.embedding_model) == ("gemini", Settings.model_fields["embedding_model"].default)


def test_an_unknown_provider_is_refused(monkeypatch):
    with pytest.raises(ValueError, match="llm_provider"):
        settings_of(monkeypatch, llm_provider="anthropic")


# ── Factories ─────────────────────────────────────────────────────────────────

def test_the_chat_model_comes_from_ollama_with_the_app_s_limits_and_needs_no_key(ollama):
    module = fresh("src.llm.llm_client")
    llm = module.get_llm()
    assert isinstance(llm, module.OllamaChat)
    assert (llm.model, llm.base_url) == (OLLAMA_LLM_MODEL, CLOSED_PORT)
    assert llm.temperature == settings.llm_temperature
    assert llm.num_ctx == settings.ollama_num_ctx
    assert llm.num_predict == settings.llm_max_output_tokens
    assert llm._client._client.timeout.read == settings.llm_timeout_seconds
    # The agent and the evaluation's judge choose their own temperature and model
    judge = module.get_llm(temperature=0.0, model="gemma3:4b")
    assert (judge.temperature, judge.model) == (0.0, "gemma3:4b")


def test_the_embeddings_come_from_ollama_and_need_no_key(ollama):
    embeddings = fresh("src.embeddings.embedder").get_embeddings()
    assert type(embeddings).__name__ == "OllamaEmbeddings"
    assert (embeddings.model, embeddings.base_url) == (OLLAMA_EMBEDDING_MODEL, CLOSED_PORT)
    assert embeddings._client._client.timeout.read == settings.embedding_timeout_seconds


# ── What the person asking is told ────────────────────────────────────────────

def test_a_stopped_ollama_is_named_and_not_retried(ollama):
    # A chat streams, and the Ollama client then lets httpx's own error through; an embedding
    # comes back whole, and the client raises a ConnectionError of its own. Both are named.
    module = fresh("src.llm.llm_client")
    llm = module.get_llm()
    with pytest.raises((ConnectionError, httpx.ConnectError)) as stopped:
        llm.invoke("Hello")
    assert llm_client.setup_problem(stopped.value) == llm_client.OLLAMA_NOT_RUNNING
    assert not llm_client.is_unavailable(stopped.value)

    with pytest.raises((ConnectionError, httpx.ConnectError)) as stopped:
        fresh("src.embeddings.embedder").get_embeddings().embed_query("Hello")
    assert llm_client.setup_problem(stopped.value) == llm_client.OLLAMA_NOT_RUNNING


def test_gemini_out_of_reach_is_not_taken_for_ollama():
    request = httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta/models/m:generateContent")
    assert llm_client.setup_problem(httpx.ConnectError("No route to host", request=request)) is None
    assert llm_client.setup_problem(httpx.ConnectError("No request attached")) is None


def wrapped(error: BaseException) -> BaseException:
    """The error as LangChain passes it on: inside an error of its own."""
    try:
        raise RuntimeError("Error calling the model") from error
    except RuntimeError as outer:
        return outer


@pytest.mark.parametrize("error,said", [
    (ResponseError('model "qwen2.5:7b" not found, try pulling it first', 404),
     "The model qwen2.5:7b is not installed in Ollama. Install it with: ollama pull qwen2.5:7b"),
    (ResponseError("registry.ollama.ai/library/gemma3:4b does not support tools", 400),
     "Agent mode needs a model that can use tools"),
    (ResponseError("model requires more system memory (5.6 GiB) than is available (3.1 GiB)", 500),
     llm_client.OLLAMA_FAILED),
    (ModelSetupError("Read the documents again first."), "Read the documents again first."),
])
def test_what_the_owner_must_fix_is_said_plainly(error, said):
    assert llm_client.setup_problem(wrapped(error)).startswith(said)
    assert not llm_client.is_unavailable(wrapped(error))


def test_the_tools_message_names_the_configured_model_and_one_that_can(monkeypatch):
    monkeypatch.setattr(settings, "llm_model", "gemma3:4b")
    said = llm_client.setup_problem(ResponseError("registry.ollama.ai/library/gemma3:4b does not support tools", 400))
    assert "gemma3:4b cannot" in said and OLLAMA_LLM_MODEL in said


def test_a_busy_ollama_is_busy_not_broken_and_is_tried_again(monkeypatch):
    busy = ResponseError("server busy, please try again", 503)
    assert llm_client.is_unavailable(wrapped(busy)) and llm_client.setup_problem(busy) is None

    class RetryingFake(llm_client.RetryWhenUnavailable, ScriptedChatModel):
        """The fake model, with the retries the real ones have."""

    monkeypatch.setattr(settings, "llm_retry_seconds", 0.0)
    llm = RetryingFake(errors=[busy])
    llm.invoke("Answer:")
    assert llm.calls == 2


@pytest.mark.parametrize("error", [ValueError("bad"), ConnectionError("Connection reset by peer"), RuntimeError("x")])
def test_other_errors_are_not_setup_problems(error):
    assert llm_client.setup_problem(error) is None
