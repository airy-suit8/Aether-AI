"""
embeddings/embedder.py — the one factory for the embedding model.

Every caller goes through get_embeddings(), so the tests replace this one function with a
fake (tests/conftest.py) and nothing reaches Google, Ollama or an OpenAI-compatible service.
"""

from google.genai import Client
from google.genai.types import HttpOptions
from langchain_core.embeddings import Embeddings
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_ollama import OllamaEmbeddings
from langchain_openai import OpenAIEmbeddings

from src.core.config import settings


class ModelSetupError(RuntimeError):
    """A model the app cannot use until its owner changes something on this computer. The message
    says what, in words for the person who asked (llm_client.setup_problem passes it on)."""


# What an OpenAI-compatible client is given as its key when none is set: the client needs one,
# and a server on this computer (LM Studio, Ollama) takes any
NO_KEY = "none"


def require_model(kind: str, model: str) -> str:
    """The model id an OpenAI-compatible service is asked for, or a ModelSetupError saying to name
    one: every service has its own ids, so there is no default."""
    if not model:
        setting = "AETHER_LLM_MODEL" if kind == "chat" else "AETHER_EMBEDDING_MODEL"
        raise ModelSetupError(f"The {kind} model runs on an OpenAI-compatible service, and no model is named. "
                              f"Set {setting} in backend/.env to a model id the service at {settings.openai_url} lists.")
    return model


def require_api_key() -> str:
    """Return the Gemini key, or stop with a clear message when it is missing."""
    if not settings.google_api_key:
        raise RuntimeError("GOOGLE_API_KEY is not set. Add it to backend/.env (see backend/.env.example).")
    return settings.google_api_key


def get_embeddings() -> Embeddings:
    """The embedding model settings.embedding_provider names, with a request timeout.

    langchain-google-genai 4.2.6 has no timeout option for embeddings (its request_options
    field is never used), so the Gemini client is rebuilt with one. An embedding has no output
    tokens, so there is no output cap to set. Ollama needs no key; building its client makes no
    request. An OpenAI-compatible service gets the texts as they are: its tokenizer is not
    OpenAI's, so LangChain's tiktoken splitting (which downloads OpenAI's tokenizer) is off.
    """
    if settings.embedding_provider == "openai":
        return OpenAIEmbeddings(model=require_model("embedding", settings.embedding_model),
                                openai_api_base=settings.openai_url, openai_api_key=settings.openai_api_key or NO_KEY,
                                request_timeout=settings.embedding_timeout_seconds, max_retries=0,
                                check_embedding_ctx_length=False)
    if settings.embedding_provider == "ollama":
        return OllamaEmbeddings(model=settings.embedding_model, base_url=settings.ollama_url,
                                client_kwargs={"timeout": settings.embedding_timeout_seconds})
    api_key = require_api_key()
    embeddings = GoogleGenerativeAIEmbeddings(model=settings.embedding_model, google_api_key=api_key)
    embeddings.client = Client(
        api_key=api_key,
        http_options=HttpOptions(timeout=int(settings.embedding_timeout_seconds * 1000)),
    )
    return embeddings
