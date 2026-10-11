"""
tests/conftest.py — Shared fixtures for the Aether AI test suite.

Creates an isolated test environment with:
  - A fresh SQLite database per test session
  - A FastAPI TestClient
  - Pre-registered test user with JWT token
"""

import os
import sys
import tempfile
import pytest

# Ensure the backend directory is on sys.path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Override database path BEFORE any backend module is imported
_test_db_dir = tempfile.mkdtemp(prefix="aether_test_")
os.environ["AETHER_DB_PATH"] = os.path.join(_test_db_dir, "test_aether.db")

# Now safe to import
from main import app  # noqa: E402
from auth import get_password_hash, create_access_token  # noqa: E402
from database import init_db, create_user, get_user_by_username  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _init_test_db():
    """Initialize a clean test database once per session."""
    init_db()
    yield


@pytest.fixture(scope="session")
def client():
    """Provide an httpx-based TestClient for the FastAPI app."""
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c


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
