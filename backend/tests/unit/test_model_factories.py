"""
The model factories (C2, S4): one place builds each Gemini client, with the model id, a
request timeout and an output cap from settings. Nothing here calls Google: building a
client makes no request.
"""

import importlib.util

import pytest

from src.core.config import settings


def fresh(module_name):
    """A private copy of a module, unaffected by the fakes conftest.py installs in the real one."""
    spec = importlib.util.find_spec(module_name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fake_key(monkeypatch):
    monkeypatch.setattr(settings, "google_api_key", "not-a-real-key")


def test_embeddings_use_the_configured_model_and_timeout(fake_key):
    embeddings = fresh("src.embeddings.embedder").get_embeddings()
    assert embeddings.model == settings.embedding_model
    assert embeddings.client._api_client._http_options.timeout == settings.embedding_timeout_seconds * 1000


def test_embeddings_without_a_key_say_so():
    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY is not set"):
        fresh("src.embeddings.embedder").get_embeddings()
