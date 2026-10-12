"""
database.py — SQLite Persistence Layer

Stores conversation history and document metadata in a local SQLite database.
Zero external dependencies — sqlite3 ships with Python. Importing this module opens nothing;
the database file is set by settings.db_path (AETHER_DB_PATH).

Tables:
  users         — accounts; each has a random tenant_id, the key of its chunks in the vector store
  conversations — stores every Q&A turn with timestamps
  documents     — tracks uploaded document metadata
"""

import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from src.core.config import settings

# Thread-safe lock for write operations
_db_lock = threading.Lock()


def _get_connection() -> sqlite3.Connection:
    """Create a connection with row factory for dict-like access."""
    conn = sqlite3.connect(str(settings.db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # Better concurrent read performance
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables if they don't exist. Called once, from the app's lifespan hook."""
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    with _db_lock:
        conn = _get_connection()

        # Step 1: Create tables (IF NOT EXISTS is a no-op on existing tables)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                tenant_id TEXT
            );

            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 1,
                session_id TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                confidence REAL DEFAULT 0.0,
                mode TEXT DEFAULT 'original',
                feedback INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 1,
                filename TEXT NOT NULL,
                file_hash TEXT,
                pages INTEGER DEFAULT 0,
                chunks INTEGER DEFAULT 0,
                size_bytes INTEGER DEFAULT 0,
                uploaded_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );
        """)

        # Step 2: Migrations — add columns that may be missing on legacy databases.
        # These must run BEFORE index creation on those columns.
        _migrate_column(conn, "conversations", "feedback", "INTEGER DEFAULT 0")
        _migrate_column(conn, "conversations", "user_id", "INTEGER DEFAULT 1")
        _migrate_column(conn, "documents", "user_id", "INTEGER DEFAULT 1")
        _migrate_column(conn, "users", "tenant_id", "TEXT")

        # Create a locked default user to adopt any orphaned pre-auth records.
        conn.execute(
            "INSERT OR IGNORE INTO users (id, username, password_hash, created_at) VALUES (1, '__legacy_migration__', '!', ?)",
            (datetime.now().isoformat(),)
        )

        # Every user gets a random tenant id, the key of their chunks in the vector store (S2).
        # User ids restart in a new database; tenant ids are never reused.
        for (user_id,) in conn.execute("SELECT id FROM users WHERE tenant_id IS NULL").fetchall():
            conn.execute("UPDATE users SET tenant_id = ? WHERE id = ?", (_new_tenant_id(), user_id))

        # Step 3: Create indexes (safe now — columns guaranteed to exist)
        conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_conv_user_session ON conversations(user_id, session_id);
            CREATE INDEX IF NOT EXISTS idx_doc_user_hash ON documents(user_id, file_hash);
        """)

        conn.commit()
        conn.close()


def _new_tenant_id() -> str:
    return str(uuid.uuid4())


def _migrate_column(conn: sqlite3.Connection, table: str, column: str, col_type: str):
    """Add a column to an existing table if it doesn't already exist."""
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type};")
    except sqlite3.OperationalError:
        pass  # Column already exists



# ── User Operations ───────────────────────────────────────────────────────────

def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    conn = _get_connection()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return dict(row) if row else None

def create_user(username: str, password_hash: str) -> int:
    with _db_lock:
        conn = _get_connection()
        cursor = conn.execute(
            "INSERT INTO users (username, password_hash, created_at, tenant_id) VALUES (?, ?, ?, ?)",
            (username, password_hash, datetime.now().isoformat(), _new_tenant_id())
        )
        conn.commit()
        user_id = cursor.lastrowid
        conn.close()
        return user_id

def get_tenant_id(user_id: int) -> str:
    """The user's tenant id, the key of their chunks in the vector store. LookupError for no such user."""
    conn = _get_connection()
    row = conn.execute("SELECT tenant_id FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if row is None or not row["tenant_id"]:
        raise LookupError(f"No user with id {user_id}")
    return row["tenant_id"]


def get_document_owners() -> List[Dict[str, Any]]:
    """Every document record with its owner's tenant id: {user_id, tenant_id, document_id, filename}."""
    conn = _get_connection()
    rows = conn.execute(
        "SELECT u.id AS user_id, u.tenant_id, d.id AS document_id, d.filename "
        "FROM documents d JOIN users u ON u.id = d.user_id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ── Conversation Operations ───────────────────────────────────────────────────

def save_conversation(user_id: int, session_id: str, question: str, answer: str,
                      confidence: float = 0.0, mode: str = "original"):
    """Save a Q&A turn to the database."""
    with _db_lock:
        conn = _get_connection()
        conn.execute(
            "INSERT INTO conversations (user_id, session_id, question, answer, confidence, mode, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, session_id, question, answer, confidence, mode, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()


def get_conversation_history(user_id: int, session_id: str, limit: int = 10) -> List[Dict[str, str]]:
    """Retrieve recent conversation history for a session."""
    conn = _get_connection()
    rows = conn.execute(
        "SELECT question, answer FROM conversations "
        "WHERE user_id = ? AND session_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, session_id, limit)
    ).fetchall()
    conn.close()
    # Reverse so oldest is first
    return [{"question": r["question"], "answer": r["answer"]} for r in reversed(rows)]


def clear_conversation(user_id: int, session_id: str):
    """Delete all conversation history for a session."""
    with _db_lock:
        conn = _get_connection()
        conn.execute("DELETE FROM conversations WHERE user_id = ? AND session_id = ?", (user_id, session_id))
        conn.commit()
        conn.close()


def update_conversation_feedback(user_id: int, session_id: str, feedback: int):
    """Update feedback (1=up, -1=down) for the most recent turn in a session."""
    with _db_lock:
        conn = _get_connection()
        # Find the max ID for the session to update the latest message
        row = conn.execute("SELECT MAX(id) as max_id FROM conversations WHERE user_id = ? AND session_id = ?", (user_id, session_id)).fetchone()
        if row and row["max_id"]:
            conn.execute("UPDATE conversations SET feedback = ? WHERE id = ?", (feedback, row["max_id"]))
            conn.commit()
        conn.close()


# ── Document Operations ───────────────────────────────────────────────────────

def save_document_record(user_id: int, filename: str, pages: int, chunks: int,
                         size_bytes: int = 0, file_hash: str = None) -> int:
    """Record a document upload in the database. Returns the document's id."""
    with _db_lock:
        conn = _get_connection()
        cursor = conn.execute(
            "INSERT INTO documents (user_id, filename, file_hash, pages, chunks, size_bytes, uploaded_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, filename, file_hash, pages, chunks, size_bytes, datetime.now().isoformat())
        )
        conn.commit()
        document_id = cursor.lastrowid
        conn.close()
    return document_id


def update_document_counts(user_id: int, document_id: int, pages: int, chunks: int):
    """Set a document's page and chunk counts once it has been ingested."""
    with _db_lock:
        conn = _get_connection()
        conn.execute("UPDATE documents SET pages = ?, chunks = ? WHERE id = ? AND user_id = ?",
                     (pages, chunks, document_id, user_id))
        conn.commit()
        conn.close()


def get_document(user_id: int, document_id: int) -> Optional[Dict[str, Any]]:
    """One of this user's documents, or None (also None for another user's document)."""
    conn = _get_connection()
    row = conn.execute("SELECT id, filename, chunks FROM documents WHERE id = ? AND user_id = ?",
                       (document_id, user_id)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_document_record(user_id: int, document_id: int):
    with _db_lock:
        conn = _get_connection()
        conn.execute("DELETE FROM documents WHERE id = ? AND user_id = ?", (document_id, user_id))
        conn.commit()
        conn.close()


def check_duplicate_document(user_id: int, file_hash: str) -> Optional[str]:
    """Check if a document with the same hash has been uploaded before. Returns filename or None."""
    conn = _get_connection()
    row = conn.execute(
        "SELECT filename FROM documents WHERE user_id = ? AND file_hash = ? LIMIT 1", (user_id, file_hash)
    ).fetchone()
    conn.close()
    return row["filename"] if row else None


def get_all_documents_detailed(user_id: int) -> List[Dict[str, Any]]:
    """Retrieve detailed metadata of all uploaded documents for a specific user."""
    conn = _get_connection()
    rows = conn.execute(
        "SELECT id, filename, file_hash, pages, chunks, size_bytes, uploaded_at FROM documents WHERE user_id = ? ORDER BY id DESC",
        (user_id,)
    ).fetchall()
    conn.close()
    return [
        {
            "id": r["id"],
            "filename": r["filename"],
            "file_hash": r["file_hash"],
            "pages": r["pages"],
            "chunks": r["chunks"],
            "size_bytes": r["size_bytes"],
            "uploaded_at": r["uploaded_at"],
        }
        for r in rows
    ]

def clear_user_documents(user_id: int):
    with _db_lock:
        conn = _get_connection()
        conn.execute("DELETE FROM documents WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()

