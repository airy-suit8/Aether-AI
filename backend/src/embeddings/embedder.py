"""
embeddings/embedder.py — the one factory for the embedding model.

Every caller goes through get_embeddings(), so the tests replace this one function with a
fake (tests/conftest.py) and nothing reaches Google.
"""

from google.genai import Client
from google.genai.types import HttpOptions
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from src.core.config import settings


def require_api_key() -> str:
    """Return the Gemini key, or stop with a clear message when it is missing."""
    if not settings.google_api_key:
        raise RuntimeError("GOOGLE_API_KEY is not set. Add it to backend/.env (see backend/.env.example).")
    return settings.google_api_key


def get_embeddings() -> GoogleGenerativeAIEmbeddings:
    """The Gemini embedding model, with a request timeout.

    langchain-google-genai 4.2.6 has no timeout option for embeddings (its request_options
    field is never used), so the client is rebuilt with one. An embedding has no output
    tokens, so there is no output cap to set.
    """
    api_key = require_api_key()
    embeddings = GoogleGenerativeAIEmbeddings(model=settings.embedding_model, google_api_key=api_key)
    embeddings.client = Client(
        api_key=api_key,
        http_options=HttpOptions(timeout=int(settings.embedding_timeout_seconds * 1000)),
    )
    return embeddings
