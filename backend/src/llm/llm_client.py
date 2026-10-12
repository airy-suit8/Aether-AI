"""
llm/llm_client.py — the one factory for the Gemini chat model.

Every caller (the pipeline, the agent, the date-time tool, the evaluation) calls
llm_client.get_llm() through the module, so the tests replace this one function with a
fake (tests/conftest.py) and nothing reaches Google.
"""

from typing import Optional

from langchain_google_genai import ChatGoogleGenerativeAI

from src.core.config import settings
from src.embeddings.embedder import require_api_key


def get_llm(temperature: Optional[float] = None, model: Optional[str] = None) -> ChatGoogleGenerativeAI:
    """The chat model, with a request timeout and a cap on output tokens.

    temperature defaults to settings.llm_temperature; tools and the agent pass
    settings.tool_temperature. model defaults to settings.llm_model; the evaluation passes
    settings.judge_model, so that answers are not scored by the model that wrote them.
    """
    return ChatGoogleGenerativeAI(
        model=model or settings.llm_model,
        google_api_key=require_api_key(),
        temperature=settings.llm_temperature if temperature is None else temperature,
        timeout=settings.llm_timeout_seconds,
        max_output_tokens=settings.llm_max_output_tokens,
    )
