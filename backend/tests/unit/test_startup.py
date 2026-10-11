"""Startup checks: the backend must refuse to start without a JWT secret (B4)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("secret", ["", "replace_with_a_long_random_string"])
def test_backend_refuses_to_start_without_jwt_secret(tmp_path, secret):
    env = {
        **os.environ,
        # Set (empty or placeholder) so load_dotenv(override=False) cannot fill it from a local .env
        "JWT_SECRET": secret,
        "AETHER_DB_PATH": str(tmp_path / "startup.db"),
        "AETHER_VECTOR_STORE_DIR": str(tmp_path / "vector_store"),
        "AETHER_LOG_DIR": str(tmp_path / "logs"),
    }
    result = subprocess.run(
        [sys.executable, "-c", "import main"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode != 0
    assert "JWT_SECRET is not set" in result.stderr


def test_backend_imports_with_jwt_secret(tmp_path):
    env = {
        **os.environ,
        "JWT_SECRET": "a-test-secret",
        "AETHER_DB_PATH": str(tmp_path / "startup.db"),
        "AETHER_VECTOR_STORE_DIR": str(tmp_path / "vector_store"),
        "AETHER_LOG_DIR": str(tmp_path / "logs"),
    }
    result = subprocess.run(
        [sys.executable, "-c", "import main"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
