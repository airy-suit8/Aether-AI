"""
core/config.py — the one source of configuration.

Every tunable (model ids, chunking, retrieval, limits, origins, data paths) is read here and
nowhere else. Values come from, highest priority first: environment variables, backend/.env,
then the defaults below. Tunables use the AETHER_ prefix (AETHER_TOP_K=8, AETHER_DB_PATH=...);
the two secrets keep their usual names, GOOGLE_API_KEY and JWT_SECRET.

Reading the settings opens nothing and needs no key: the key is checked when a model is built,
and the JWT secret when the app is built (main.create_app).
"""

from pathlib import Path
from typing import List, Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]

# Shown by /health and the OpenAPI schema. Not a tunable.
APP_VERSION = "2.0.0"

# The value .env.example ships with: treated as unset.
JWT_SECRET_PLACEHOLDER = "replace_with_a_long_random_string"


class Settings(BaseSettings):
    """Application settings: environment variables win over backend/.env, which wins over these defaults."""

    model_config = SettingsConfigDict(
        env_prefix="AETHER_",
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Secrets (their usual names, no prefix) ────────────────────────────────
    google_api_key: str = Field(default="", validation_alias="GOOGLE_API_KEY")
    jwt_secret: str = Field(default="", validation_alias="JWT_SECRET")
    access_token_minutes: int = 60 * 24 * 7  # 1 week

    # ── Models ────────────────────────────────────────────────────────────────
    llm_model: str = "gemini-3.5-flash"
    llm_temperature: float = 0.3
    tool_temperature: float = 0.0          # the agent, the date-time tool and the evaluation judge
    llm_timeout_seconds: float = 120.0
    llm_max_output_tokens: int = 8192
    embedding_model: str = "models/gemini-embedding-001"
    embedding_timeout_seconds: float = 60.0

    # ── RAG pipeline ──────────────────────────────────────────────────────────
    document_loader: Literal["native", "langchain"] = "native"
    chunk_size: int = 1000
    chunk_overlap: int = 150
    top_k: int = 5
    confidence_threshold: float = 0.3      # minimum best cosine similarity to answer (Task 7)
    memory_max_turns: int = 10             # conversation turns remembered per session (Task 4)
    agent_recursion_limit: int = 12        # LangGraph steps per agent question; each tool call takes two

    # ── Server and limits ─────────────────────────────────────────────────────
    allowed_origins: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    max_upload_bytes: int = 50 * 1024 * 1024
    max_question_chars: int = 5000
    rate_limit_register: str = "5/minute"
    rate_limit_login: str = "10/minute"
    rate_limit_upload: str = "10/minute"
    rate_limit_chat: str = "30/minute"

    # ── Data paths (AETHER_DB_PATH, AETHER_VECTOR_STORE_DIR, AETHER_LOG_DIR) ──
    db_path: Path = BACKEND_DIR / "aether.db"
    vector_store_dir: Path = BACKEND_DIR / "vector_store"
    log_dir: Path = BACKEND_DIR / "logs"

    def require_jwt_secret(self) -> str:
        """Return the JWT secret, or stop with a clear message when it is missing."""
        if not self.jwt_secret or self.jwt_secret == JWT_SECRET_PLACEHOLDER:
            raise RuntimeError(
                "JWT_SECRET is not set. Add it to backend/.env (see backend/.env.example). "
                "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
            )
        return self.jwt_secret


# Module-level singleton: import this, never read os.environ elsewhere.
settings = Settings()
