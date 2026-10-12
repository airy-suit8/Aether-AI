"""
llm/llm_client.py — the one factory for the Gemini chat model, and what to do when it is busy.

Every caller (the pipeline, the agent, the date-time tool, the evaluation) calls
llm_client.get_llm() through the module, so the tests replace this one function with a
fake (tests/conftest.py) and nothing reaches Google.

A call that fails because Gemini is over its quota or unavailable is tried again after a pause
(B10, RetryWhenUnavailable); is_unavailable() tells the routes to answer with MODEL_BUSY instead
of a general server error.
"""

import logging
import time
from typing import Optional

from google.genai import errors as genai_errors
from langchain_google_genai import ChatGoogleGenerativeAI

from src.core.config import settings
from src.core.logging import error_logger, log_event
from src.embeddings.embedder import require_api_key

# Quota (429) and availability (500, 502, 503, 504): worth another try after a pause. Anything else
# (a bad request, a wrong key, a model that does not exist) would fail the same way again.
RETRY_CODES = frozenset({429, 500, 502, 503, 504})

# What the person asking is told when every try failed for one of those reasons
MODEL_BUSY = "The AI service is busy or over its usage limit right now. Please try again in a minute."


def unavailable_code(exc: BaseException) -> Optional[int]:
    """The quota or availability status behind an error, or None. LangChain wraps Gemini's client
    errors in its own exception, so the causes are followed too."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, genai_errors.APIError) and exc.code in RETRY_CODES:
            return exc.code
        exc = exc.__cause__ or exc.__context__
    return None


def is_unavailable(exc: BaseException) -> bool:
    """True when an error means Gemini was over its quota or unavailable (also for embeddings)."""
    return unavailable_code(exc) is not None


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


def get_llm(temperature: Optional[float] = None, model: Optional[str] = None) -> ChatGoogleGenerativeAI:
    """The chat model, with a request timeout, a cap on output tokens and the app's retries.

    temperature defaults to settings.llm_temperature; tools and the agent pass
    settings.tool_temperature. model defaults to settings.llm_model; the evaluation passes
    settings.judge_model, so that answers are not scored by the model that wrote them.
    """
    return GeminiChat(
        model=model or settings.llm_model,
        google_api_key=require_api_key(),
        temperature=settings.llm_temperature if temperature is None else temperature,
        timeout=settings.llm_timeout_seconds,
        max_output_tokens=settings.llm_max_output_tokens,
        # 1 means a single call: the Google client's own retries are off (0 would mean its default, 5)
        max_retries=1,
    )
