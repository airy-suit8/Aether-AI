"""
config.py — Centralized Configuration Management

All application settings in one place using Pydantic BaseSettings.
No more hardcoded values scattered across 4+ files.
"""

import os
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv(override=True)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # ── API Keys ──────────────────────────────────────────────────────────────
    google_api_key: str = os.environ.get("GOOGLE_API_KEY", "")

    # ── Application ───────────────────────────────────────────────────────────
    app_title: str = "Aether AI — Knowledge Assistant API"
    app_description: str = "A Retrieval-Augmented Generation chatbot powered by Google Gemini"
    app_version: str = "3.0.0"

    # ── LLM Configuration ────────────────────────────────────────────────────
    embedding_model: str = "models/gemini-embedding-001"
    llm_model: str = "gemini-3.5-flash"
    llm_temperature: float = 0.3

    # ── RAG Pipeline ──────────────────────────────────────────────────────────
    chunk_size: int = 1000
    chunk_overlap: int = 150
    top_k: int = 5
    confidence_threshold: float = 0.3
    memory_max_turns: int = 10
    embedding_batch_size: int = 100

    # ── Server ────────────────────────────────────────────────────────────────
    allowed_origins: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    max_file_size_mb: int = 50
    rate_limit_chat: str = "30/minute"
    rate_limit_upload: str = "10/minute"

    # ── File Support ──────────────────────────────────────────────────────────
    allowed_extensions: List[str] = [".pdf", ".txt", ".md", ".markdown", ".docx", ".csv", ".xlsx", ".xls"]

    # ── Paths ─────────────────────────────────────────────────────────────────
    base_dir: Path = Path(__file__).parent
    vector_store_dir: Path = Path(__file__).parent / "vector_store"
    db_path: Path = Path(__file__).parent / "aether.db"

    class Config:
        env_file = ".env"
        extra = "allow"

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024


# Module-level singleton
settings = Settings()
