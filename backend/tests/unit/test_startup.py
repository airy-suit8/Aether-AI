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


IMPORT_EVERY_MODULE = """
import importlib, pathlib
for path in sorted(pathlib.Path("src").rglob("*.py")):
    importlib.import_module(".".join(path.with_suffix("").parts).removesuffix(".__init__"))
import main
"""


def test_importing_every_module_opens_nothing_and_needs_no_key(tmp_path):
    # C3: no database, vector store or log folder at import, and no Gemini key needed
    env = {
        **os.environ,
        "JWT_SECRET": "a-test-secret",
        "GOOGLE_API_KEY": "",
        "AETHER_DB_PATH": str(tmp_path / "data" / "startup.db"),
        "AETHER_VECTOR_STORE_DIR": str(tmp_path / "vector_store"),
        "AETHER_LOG_DIR": str(tmp_path / "logs"),
    }
    result = subprocess.run(
        [sys.executable, "-c", IMPORT_EVERY_MODULE],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []


def test_src_modules_import_without_a_jwt_secret(tmp_path):
    # Only building the app (main.create_app) needs the secret
    env = {**os.environ, "JWT_SECRET": "", "AETHER_LOG_DIR": str(tmp_path / "logs")}
    script = IMPORT_EVERY_MODULE.replace("import main\n", "")
    result = subprocess.run([sys.executable, "-c", script], cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
