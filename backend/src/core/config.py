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

from pydantic import Field, PrivateAttr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
# The database and the vector store live together in one folder at the project root (S2)
DATA_DIR = BACKEND_DIR.parent / "data"
# Where they were kept before Sprint 5; a store found there is still used (see Settings)
OLD_DB_PATH = BACKEND_DIR / "aether.db"
OLD_VECTOR_STORE_DIR = BACKEND_DIR / "vector_store"

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
    tool_temperature: float = 0.0          # the agent and the evaluation judge
    llm_timeout_seconds: float = 120.0
    llm_max_output_tokens: int = 8192
    embedding_model: str = "models/gemini-embedding-001"
    embedding_timeout_seconds: float = 60.0
    # The evaluation's judge (AETHER_JUDGE_MODEL). It must differ from llm_model, so it has no
    # default: an answer scored by the model that wrote it is not a measurement.
    judge_model: str = ""

    # ── RAG pipeline ──────────────────────────────────────────────────────────
    document_loader: Literal["native", "langchain"] = "native"
    chunk_size: int = 1000
    chunk_overlap: int = 150
    top_k: int = 5
    confidence_threshold: float = 0.3      # minimum best cosine similarity to answer (Task 7)
    # What the answer is written from. "summary": a model summary of the retrieved chunks (two
    # model calls). "chunks": the numbered chunks themselves, cited as [1], [2] (one call; the
    # sources are then the chunks cited). The default changes only when the evaluation shows
    # which is better (R4, R5).
    answer_from: Literal["summary", "chunks"] = "summary"
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
    db_path: Path = Field(default_factory=lambda: DATA_DIR / "aether.db")
    vector_store_dir: Path = Field(default_factory=lambda: DATA_DIR / "vector_store")
    log_dir: Path = BACKEND_DIR / "logs"

    _path_notes: List[str] = PrivateAttr(default_factory=list)

    @model_validator(mode="after")
    def _keep_using_stores_at_the_old_default_paths(self) -> "Settings":
        """A store made before Sprint 5, at the old default path, is used rather than starting
        empty, when its path was not set and nothing exists at the new default yet. Nothing is
        moved; path_notes() says what was found, for the startup log."""
        for field, old in (("db_path", OLD_DB_PATH), ("vector_store_dir", OLD_VECTOR_STORE_DIR)):
            # The module names are read here, not at import, so a test can point them elsewhere
            new = getattr(self, field)
            if field in self.model_fields_set or new.exists() or not old.exists():
                continue
            setattr(self, field, old)
            self._path_notes.append(
                f"Using {old}, the old default path, because nothing is at the new default {new}. "
                f"To stop this note, move it there with the backend stopped, or set AETHER_{field.upper()}.")
        return self

    def path_notes(self) -> List[str]:
        """What the startup should log about where the stores were found."""
        return list(self._path_notes)

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
