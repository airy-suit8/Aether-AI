"""
llm/llm_client.py — the one factory for the chat model, and what to do when it is busy.

Every caller (the pipeline, the agent, the date-time tool, the evaluation) calls
llm_client.get_llm() through the module, so the tests replace this one function with a
fake (tests/conftest.py) and nothing reaches Google or Ollama.

The model is Gemini, or a model on this computer through Ollama (settings.llm_provider). A call
that fails because the model is over its quota or unavailable is tried again after a pause
(B10, RetryWhenUnavailable); is_unavailable() tells the routes to answer with MODEL_BUSY instead
of a general server error, and setup_problem() names what the owner must fix (Ollama not
running, a model not installed) instead of a general server error.
"""

import logging
import re
import time
from typing import Iterator, Optional

import httpx
from google.genai import errors as genai_errors
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from ollama import ResponseError as OllamaResponseError

from src.core.config import OLLAMA_LLM_MODEL, settings
from src.core.logging import error_logger, log_event
from src.embeddings.embedder import ModelSetupError, require_api_key

# Quota (429) and availability (500, 502, 503, 504): worth another try after a pause. Anything else
# (a bad request, a wrong key, a model that does not exist) would fail the same way again.
RETRY_CODES = frozenset({429, 500, 502, 503, 504})
# Ollama answers 503 when its queue is full. Its 500s are not passing: a model too large for the
# memory, or a damaged download, fails the same way again.
OLLAMA_RETRY_CODES = frozenset({429, 503})

# What the person asking is told when every try failed for one of those reasons
MODEL_BUSY = "The AI service is busy or over its usage limit right now. Please try again in a minute."

OLLAMA_NOT_RUNNING = "The AI model runs on this computer through Ollama, and Ollama is not running. Start Ollama, then try again."
OLLAMA_FAILED = "Ollama could not run the AI model. The server's error log says why."


def _causes(exc: Optional[BaseException]) -> Iterator[BaseException]:
    """The error and every error behind it: LangChain wraps the clients' errors in its own."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        yield exc
        exc = exc.__cause__ or exc.__context__


def unavailable_code(exc: BaseException) -> Optional[int]:
    """The quota or availability status behind an error, or None."""
    for cause in _causes(exc):
        if isinstance(cause, genai_errors.APIError) and cause.code in RETRY_CODES:
            return cause.code
        if isinstance(cause, OllamaResponseError) and cause.status_code in OLLAMA_RETRY_CODES:
            return cause.status_code
    return None


def is_unavailable(exc: BaseException) -> bool:
    """True when an error means the model was over its quota or unavailable (also for embeddings)."""
    return unavailable_code(exc) is not None


def _requested_path(exc: httpx.RequestError) -> str:
    """The path of the request an httpx error came from, or "" when it carries none."""
    try:
        return exc.request.url.path
    except RuntimeError:
        return ""


def setup_problem(exc: BaseException) -> Optional[str]:
    """What the owner must change on this computer before the model can answer, in words for the
    person who asked, or None when the error is not of that kind."""
    for cause in _causes(exc):
        if isinstance(cause, ModelSetupError):
            return str(cause)
        # The Ollama client turns a refused connection into this, with its own message; except when
        # streaming, where httpx's own error comes through. Ollama's paths start with /api/, and
        # Google's never do, so Gemini out of reach is not taken for Ollama.
        if isinstance(cause, ConnectionError) and "Ollama" in str(cause):
            return OLLAMA_NOT_RUNNING
        if isinstance(cause, httpx.ConnectError) and _requested_path(cause).startswith("/api/"):
            return OLLAMA_NOT_RUNNING
        if isinstance(cause, OllamaResponseError) and cause.status_code not in OLLAMA_RETRY_CODES:
            missing = re.search(r'model "([^"]+)" not found', cause.error)
            if missing:
                name = missing.group(1)
                return f"The model {name} is not installed in Ollama. Install it with: ollama pull {name}"
            if "does not support tools" in cause.error:
                return (f"Agent mode needs a model that can use tools, and {settings.llm_model} cannot. Ask in "
                        f"Default or Hybrid mode, or set AETHER_LLM_MODEL to one that can, such as {OLLAMA_LLM_MODEL}.")
            return OLLAMA_FAILED
    return None


def _pause_before_retry(attempt: int, exc: BaseException) -> None:
    seconds = settings.llm_retry_seconds * 2 ** (attempt - 1)
    log_event(error_logger, "model_retry", level=logging.WARNING, status=unavailable_code(exc),
              attempt=attempt, wait_seconds=seconds)
    time.sleep(seconds)


class RetryWhenUnavailable:
    """
    Mixed into a LangChain chat model: a call that fails for quota or availability is made again,
    up to settings.llm_max_attempts calls, after a pause that doubles each time (B10). A stream is
    tried again only if the error came before its first piece: once words have been sent, the
    error is passed on rather than repeating them.
    """

    def _generate(self, *args, **kwargs):
        attempt = 1
        while True:
            try:
                return super()._generate(*args, **kwargs)
            except Exception as e:
                if attempt >= settings.llm_max_attempts or not is_unavailable(e):
                    raise
                _pause_before_retry(attempt, e)
                attempt += 1

    def _stream(self, *args, **kwargs):
        attempt = 1
        while True:
            started = False
            try:
                for chunk in super()._stream(*args, **kwargs):
                    started = True
                    yield chunk
                return
            except Exception as e:
                if started or attempt >= settings.llm_max_attempts or not is_unavailable(e):
                    raise
                _pause_before_retry(attempt, e)
                attempt += 1


class GeminiChat(RetryWhenUnavailable, ChatGoogleGenerativeAI):
    """The Gemini chat model, with the app's retries in place of the Google client's."""


class OllamaChat(RetryWhenUnavailable, ChatOllama):
    """A chat model on this computer, served by Ollama, with the app's retries."""


def get_llm(temperature: Optional[float] = None, model: Optional[str] = None) -> BaseChatModel:
    """The chat model, with a request timeout, a cap on output tokens and the app's retries.

    temperature defaults to settings.llm_temperature; tools and the agent pass
    settings.tool_temperature. model defaults to settings.llm_model; the evaluation passes
    settings.judge_model, so that answers are not scored by the model that wrote them.
    Building either model makes no request.
    """
    if settings.llm_provider == "ollama":
        return OllamaChat(
            model=model or settings.llm_model,
            base_url=settings.ollama_url,
            temperature=settings.llm_temperature if temperature is None else temperature,
            num_ctx=settings.ollama_num_ctx,
            num_predict=settings.llm_max_output_tokens,
            reasoning=settings.ollama_think,
            keep_alive=settings.ollama_keep_alive,
            client_kwargs={"timeout": settings.llm_timeout_seconds},
        )
    return GeminiChat(
        model=model or settings.llm_model,
        google_api_key=require_api_key(),
        temperature=settings.llm_temperature if temperature is None else temperature,
        timeout=settings.llm_timeout_seconds,
        max_output_tokens=settings.llm_max_output_tokens,
        # 1 means a single call: the Google client's own retries are off (0 would mean its default, 5)
        max_retries=1,
    )
