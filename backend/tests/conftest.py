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
os.environ["OPENAI_API_KEY"] = ""  # the same for an OpenAI-compatible service
# The suite tests the default providers (with fake models): a provider chosen in backend/.env,
# such as Ollama, is not read here.
os.environ["AETHER_LLM_PROVIDER"] = "gemini"
os.environ["AETHER_EMBEDDING_PROVIDER"] = "gemini"
# No reranking model either: it would be downloaded. The reranker's tests give it a fake one.
os.environ["AETHER_RERANK_MODEL"] = ""
os.environ["AETHER_MODEL_DIR"] = os.path.join(_test_dir, "models")
os.environ["AETHER_FILES_DIR"] = os.path.join(_test_dir, "files")

# Now safe to import
from fakes import FakeOcr, HashingEmbeddings, ScriptedChatModel  # noqa: E402
from src.embeddings import embedder  # noqa: E402
from src.ingestion import ocr  # noqa: E402
from src.llm import llm_client  # noqa: E402

# The vector store opens lazily; give it fake embeddings before anything touches it.
embedder.get_embeddings = lambda: HashingEmbeddings()
# OCR reads nothing unless a test gives it pages to read (tests/unit/test_ocr.py)
ocr._load = lambda: FakeOcr()

from main import app  # noqa: E402
from src.api.deps import limiter  # noqa: E402
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
    """Replace the one chat model factory with a scripted fake, fresh per test: covers every mode and tool."""
    llm = ScriptedChatModel()
    monkeypatch.setattr(llm_client, "get_llm", lambda **kwargs: llm)
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
    from src.db.database import get_tenant_id
    token = create_access_token(
        data={"sub": str(test_user["id"]), "tid": get_tenant_id(test_user["id"])},
        expires_delta=timedelta(hours=1),
    )
    return {"Authorization": f"Bearer {token}"}
