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
from typing import List, Literal, Optional

from pydantic import Field, PrivateAttr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
# The database and the vector store live together in one folder at the project root (S2)
DATA_DIR = BACKEND_DIR.parent / "data"
# Where they were kept before Sprint 5; a store found there is still used (see Settings)
OLD_DB_PATH = BACKEND_DIR / "aether.db"
OLD_VECTOR_STORE_DIR = BACKEND_DIR / "vector_store"

# Shown in the OpenAPI schema. Not a tunable.
APP_VERSION = "2.0.0"

# The value .env.example ships with: treated as unset.
JWT_SECRET_PLACEHOLDER = "replace_with_a_long_random_string"

# The models used through Ollama unless AETHER_LLM_MODEL or AETHER_EMBEDDING_MODEL names others.
# The chat model can call tools (agent mode needs that) and fits in 6 GB of graphics memory with
# the context below. This one since 15 Oct 2026: on the owner's papers it answered 5 of 6
# questions right, against 3 of 6 for Qwen 2.5 7B, which did not fit the GPU (SPRINT_PLAN.md,
# "Document scope"). It needs Ollama 0.40 or later.
OLLAMA_LLM_MODEL = "qwen3.5:4b"
OLLAMA_EMBEDDING_MODEL = "nomic-embed-text"
GEMINI_EMBEDDING_MODEL = "models/gemini-embedding-001"

# The average similarity of an answer's passages at which it reads as grounded (the ring under an
# answer), for each embedding model, since each spreads its scores differently. Gemini: from the
# first real run (answerable questions 0.67 to 0.80, an unrelated one 0.50), until Sprint 4
# measures it. nomic-embed-text: on the owner's three documents, 15 Oct 2026 (SPRINT_PLAN.md,
# "Reranking"): 20 full questions averaged 0.61 to 0.78 and 13 short ones ("which dataset",
# "who are the authors") 0.40 to 0.67, while 6 unrelated ones ("what is the price of gold")
# averaged 0.38 to 0.48; at 0.5, 28 of the 33 read as grounded and none of the 6.
GROUNDED_LINES = {f"gemini:{GEMINI_EMBEDDING_MODEL}": 0.6, f"ollama:{OLLAMA_EMBEDDING_MODEL}": 0.5}
GROUNDED_LINE_UNMEASURED = 0.6


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

    # ── Sign-in (S7) ──────────────────────────────────────────────────────────
    # An access token is short-lived; the browser renews it with a refresh token, kept in an
    # httpOnly cookie that page scripts cannot read, and renewed with it: signing in again is
    # needed after a week without use.
    access_token_minutes: int = 30
    refresh_token_days: int = 7
    # Send the refresh cookie over HTTPS only. Turn on once the app is served over HTTPS.
    cookie_secure: bool = False
    # Registration needs this code when it is set (AETHER_INVITE_CODE). Empty: anyone can register.
    invite_code: str = ""

    # ── Models ────────────────────────────────────────────────────────────────
    # Where each model runs: "gemini", Google's API (needs GOOGLE_API_KEY), or "ollama", a model
    # on this computer served by Ollama (no key, no quota). With "ollama" the model ids below
    # default to OLLAMA_LLM_MODEL and OLLAMA_EMBEDDING_MODEL. Passages embedded by one embedding
    # model cannot be searched with another: after changing it, run python -m src.reembed.
    llm_provider: Literal["gemini", "ollama"] = "gemini"
    embedding_provider: Literal["gemini", "ollama"] = "gemini"
    ollama_url: str = "http://127.0.0.1:11434"
    # The context Ollama gives a chat model, in tokens. Ollama's own default (2048 or 4096,
    # depending on its version) cuts a long prompt from the start, which would drop the
    # instructions; this holds them, five passages and the remembered conversation.
    ollama_num_ctx: int = 8192
    # A model that can think before it answers (qwen3.5, gemma4) does not, unless this is set:
    # thinking made an answer several times slower on a laptop. How long Ollama keeps the model
    # loaded after a question: loading it again takes seconds.
    ollama_think: bool = False
    ollama_keep_alive: str = "30m"
    llm_model: str = "gemini-3.5-flash"
    llm_temperature: float = 0.3
    tool_temperature: float = 0.0          # the agent and the evaluation judge
    llm_timeout_seconds: float = 120.0
    # A model call that fails for quota (429) or availability (500, 502, 503, 504) is tried again,
    # up to llm_max_attempts calls in all, after llm_retry_seconds, then twice that, and so on (B10).
    # Any other failure is not retried. The Google client's own retries are off: they retried
    # six times, which held a request for about 60 s during the Gemini outage of 12 Oct 2026.
    llm_max_attempts: int = 3
    llm_retry_seconds: float = 2.0
    llm_max_output_tokens: int = 8192
    embedding_model: str = GEMINI_EMBEDDING_MODEL
    embedding_timeout_seconds: float = 60.0
    # The evaluation's judge (AETHER_JUDGE_MODEL). It must differ from llm_model, so it has no
    # default: an answer scored by the model that wrote it is not a measurement.
    judge_model: str = ""

    # ── RAG pipeline ──────────────────────────────────────────────────────────
    document_loader: Literal["native", "langchain"] = "native"
    chunk_size: int = 1000
    chunk_overlap: int = 150
    top_k: int = 5
    # The best passage's similarity under which a question is refused without asking the model
    # (Task 7). Not raised for nomic-embed-text: short questions about the documents ("orcid ids",
    # 0.42) scored below unrelated ones ("who is the prime minister of India", 0.52), so a line
    # that refused those refused real questions too; the model says when the passages do not answer.
    confidence_threshold: float = 0.3
    # The line of GROUNDED_LINES for the embedding model, unless set (AETHER_GROUNDED_AT)
    grounded_at: Optional[float] = None
    # What the answer is written from. "chunks": the numbered chunks themselves, cited as [1],
    # [2] (one model call; the sources are then the chunks cited). "summary": a model summary of
    # the retrieved chunks, then the answer from it (two calls). "chunks" is the default since
    # 15 Oct 2026: on the owner's papers the summary dropped exact details (ORCID ids) and doubled
    # the time on a local model (R4, R5; SPRINT_PLAN.md, "Document scope").
    answer_from: Literal["summary", "chunks"] = "chunks"
    # How many passages either side of the two best hits are read with them, for the context
    # around a passage (Verba's "chunk window"). 0: none.
    chunk_window: int = 1
    # Reranking: a search finds rerank_candidates passages, then a cross-encoder model on this
    # computer reads the question with each one and keeps the top_k that answer it best. kotaemon
    # and bRAG rerank the same way, through Cohere's API. "" turns it off. The model (about 90 MB)
    # is downloaded from Hugging Face the first time, into model_dir, and runs on the processor.
    # On the owner's papers it brought the passage with a paper's own result into the five read,
    # where search alone had left it sixth, behind a cited study's (SPRINT_PLAN.md, "Reranking").
    rerank_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    rerank_candidates: int = 20
    memory_max_turns: int = 10            # conversation turns remembered per session (Task 4)
    agent_recursion_limit: int = 12        # LangGraph steps per agent question; each tool call takes two

    # ── Server and limits ─────────────────────────────────────────────────────
    # "production" turns off the API pages (/docs, /redoc, /openapi.json). Set it on any machine
    # other people can reach (AETHER_ENVIRONMENT=production).
    environment: Literal["development", "production"] = "development"
    allowed_origins: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    # Uploads (S4): the file is streamed to disk and refused once it passes max_upload_bytes
    max_upload_bytes: int = 50 * 1024 * 1024
    max_unpacked_bytes: int = 200 * 1024 * 1024   # a .docx or .xlsx (zip files) once unpacked
    max_table_rows: int = 100_000                 # rows across all the sheets of a CSV or Excel file
    max_chunks_per_document: int = 5_000
    max_documents_per_user: int = 100
    max_question_chars: int = 5000
    # Per signed-in user, or per address for requests without a valid token (S8)
    rate_limit_default: str = "120/minute"   # every route without a limit of its own
    rate_limit_register: str = "5/minute"
    rate_limit_login: str = "10/minute"
    rate_limit_upload: str = "10/minute"
    rate_limit_chat: str = "30/minute"

    # ── Data paths (AETHER_DB_PATH, AETHER_VECTOR_STORE_DIR, AETHER_LOG_DIR, AETHER_MODEL_DIR) ──
    db_path: Path = Field(default_factory=lambda: DATA_DIR / "aether.db")
    vector_store_dir: Path = Field(default_factory=lambda: DATA_DIR / "vector_store")
    model_dir: Path = Field(default_factory=lambda: DATA_DIR / "models")  # models run by the app itself (reranking)
    log_dir: Path = BACKEND_DIR / "logs"

    _path_notes: List[str] = PrivateAttr(default_factory=list)

    @model_validator(mode="after")
    def _ollama_models_unless_named(self) -> "Settings":
        """With a provider of "ollama", a model id that was not set is Ollama's default, not Gemini's."""
        if self.llm_provider == "ollama" and "llm_model" not in self.model_fields_set:
            self.llm_model = OLLAMA_LLM_MODEL
        if self.embedding_provider == "ollama" and "embedding_model" not in self.model_fields_set:
            self.embedding_model = OLLAMA_EMBEDDING_MODEL
        return self

    def grounded_line(self) -> float:
        """The average similarity at which an answer reads as grounded, for the embedding model in use."""
        if self.grounded_at is not None:
            return self.grounded_at
        return GROUNDED_LINES.get(self.embedding_label(), GROUNDED_LINE_UNMEASURED)

    def embedding_label(self) -> str:
        """The embedding model as the vector store records it: provider and model id."""
        return f"{self.embedding_provider}:{self.embedding_model}"

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
