"""
tests/conftest.py — Shared fixtures for the Aether AI test suite.

Creates an isolated test environment with:
  - A fresh SQLite database, vector store and log directory in a temp folder
  - Fake embeddings and a fake chat model in place of Gemini (no API key, no network)
  - A FastAPI TestClient and helpers to register and log in users over HTTP
"""

import os
import sys
import tempfile
import uuid

import pytest

# Ensure the backend directory is on sys.path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Point every store at a temp folder BEFORE any backend module is imported
_test_dir = tempfile.mkdtemp(prefix="aether_test_")
os.environ["AETHER_DB_PATH"] = os.path.join(_test_dir, "test_aether.db")
os.environ["AETHER_VECTOR_STORE_DIR"] = os.path.join(_test_dir, "vector_store")
os.environ["AETHER_LOG_DIR"] = os.path.join(_test_dir, "logs")
os.environ["JWT_SECRET"] = "test-secret-used-only-by-the-test-suite"
# Set but empty: load_dotenv(override=False) then cannot copy a real key from backend/.env
# into the test process, so nothing here can reach Gemini even on a developer machine.
os.environ["GOOGLE_API_KEY"] = ""

# Now safe to import
import rag_engine  # noqa: E402
import rag_langchain  # noqa: E402
import agent  # noqa: E402
import tools  # noqa: E402
from fakes import HashingEmbeddings, ScriptedChatModel  # noqa: E402

# The vector store opens lazily; give it fake embeddings before anything touches it.
rag_engine._get_embeddings = lambda: HashingEmbeddings()

from main import app, limiter  # noqa: E402
from src.core.security import get_password_hash, create_access_token  # noqa: E402
from src.db.database import init_db, create_user  # noqa: E402


def pytest_addoption(parser):
    parser.addoption("--update-openapi-snapshot", action="store_true",
                     help="rewrite tests/openapi_snapshot.json from the current API instead of comparing")


@pytest.fixture(scope="session", autouse=True)
def _init_test_db():
    """Initialize a clean test database once per session."""
    init_db()
    yield


@pytest.fixture(autouse=True)
def fake_llm(monkeypatch):
    """Replace every Gemini chat model factory with one scripted fake, fresh per test."""
    llm = ScriptedChatModel()
    monkeypatch.setattr(rag_engine, "_get_llm", lambda: llm)
    monkeypatch.setattr(rag_langchain, "_get_llm", lambda: llm)
    if hasattr(agent, "_get_llm"):
        monkeypatch.setattr(agent, "_get_llm", lambda: llm)
    # The date-time tool builds its own Gemini client inline
    monkeypatch.setattr(tools, "ChatGoogleGenerativeAI", lambda **kwargs: llm)
    return llm


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """Each test starts with empty rate-limit buckets (all TestClient calls share one IP)."""
    limiter.reset()
    yield


@pytest.fixture(scope="session")
def client():
    """Provide an httpx-based TestClient for the FastAPI app."""
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c


@pytest.fixture
def make_user(client):
    """Register and log in a new user through the API; returns (username, auth headers)."""
    def _make(prefix: str = "user"):
        username = f"{prefix}_{uuid.uuid4().hex[:8]}"
        password = "securepass123"
        r = client.post("/api/v1/auth/register", json={"username": username, "password": password})
        assert r.status_code == 200, r.text
        r = client.post("/api/v1/auth/login", data={"username": username, "password": password})
        assert r.status_code == 200, r.text
        return username, {"Authorization": f"Bearer {r.json()['access_token']}"}
    return _make


@pytest.fixture(scope="session")
def test_user():
    """Create a test user and return its credentials dict."""
    username = "test_sprint8"
    password = "securepass123"
    hashed = get_password_hash(password)
    user_id = create_user(username, hashed)
    return {"id": user_id, "username": username, "password": password}


@pytest.fixture(scope="session")
def auth_headers(test_user):
    """Return Authorization headers with a valid JWT for the test user."""
    from datetime import timedelta
    token = create_access_token(
        data={"sub": str(test_user["id"])},
        expires_delta=timedelta(hours=1),
    )
    return {"Authorization": f"Bearer {token}"}
