"""
database.py — SQLite Persistence Layer

Stores conversation history and document metadata in a local SQLite database.
Zero external dependencies — sqlite3 ships with Python. Importing this module opens nothing;
the database file is set by settings.db_path (AETHER_DB_PATH).

Tables:
  users         — accounts; each has a random tenant_id, the key of its chunks in the vector store
  conversations — stores every Q&A turn with timestamps, and the sources and tool shown with it
  documents     — tracks uploaded document metadata, and whether each is processing, ready or
                  failed (it is read in the background after the upload is accepted, R12)
  session_titles — the name a user gave a conversation; without one it is titled by its first
                  question (Sprint 8, item 3)
  refresh_tokens — every refresh token issued, by its id (jti), and whether it was revoked. A
                  refresh token not listed here is refused (Sprint 8, item 4)
  shared_sessions — the conversations their owners have shared, each by an unguessable token:
                  anyone who has the link can read that one conversation, signed in or not
"""

import json
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
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
                sources TEXT,
                tool_used TEXT,
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
                status TEXT NOT NULL DEFAULT 'ready',
                error TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS session_titles (
                user_id INTEGER NOT NULL,
                session_id TEXT NOT NULL,
                title TEXT NOT NULL,
                PRIMARY KEY (user_id, session_id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS refresh_tokens (
                jti TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                issued_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                revoked_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS shared_sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                session_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (user_id, session_id),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
        """)

        # Step 2: Migrations — add columns that may be missing on legacy databases.
        # These must run BEFORE index creation on those columns.
        _migrate_column(conn, "conversations", "feedback", "INTEGER DEFAULT 0")
        _migrate_column(conn, "conversations", "user_id", "INTEGER DEFAULT 1")
        _migrate_column(conn, "documents", "user_id", "INTEGER DEFAULT 1")
        _migrate_column(conn, "users", "tenant_id", "TEXT")
        # What an answer showed with it, so a reloaded conversation shows it again (Sprint 5 item 7)
        _migrate_column(conn, "conversations", "sources", "TEXT")
        _migrate_column(conn, "conversations", "tool_used", "TEXT")
        # Documents uploaded before ingestion moved to the background were all read in full
        _migrate_column(conn, "documents", "status", "TEXT NOT NULL DEFAULT 'ready'")
        _migrate_column(conn, "documents", "error", "TEXT")

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
            CREATE INDEX IF NOT EXISTS idx_refresh_user ON refresh_tokens(user_id);
        """)

        # Usernames are unique regardless of ASCII case (S7). A database that already holds two
        # names differing only in case cannot take the index; registration still checks, case-blind.
        try:
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_nocase ON users(username COLLATE NOCASE)")
        except sqlite3.IntegrityError:
            pass

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
    """The user with this name, ignoring ASCII case (an exact match first, for an older database
    that holds two names differing only in case)."""
    conn = _get_connection()
    row = conn.execute(
        "SELECT * FROM users WHERE username = ? COLLATE NOCASE ORDER BY username = ? DESC LIMIT 1",
        (username, username),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    conn = _get_connection()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def create_user(username: str, password_hash: str) -> int:
    """Add a user and return their id. sqlite3.IntegrityError when the name is taken (in any case)."""
    with _db_lock:
        conn = _get_connection()
        try:
            cursor = conn.execute(
                "INSERT INTO users (username, password_hash, created_at, tenant_id) VALUES (?, ?, ?, ?)",
                (username, password_hash, datetime.now().isoformat(), _new_tenant_id())
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            # Also when the insert fails: a connection left open keeps its write lock
            conn.close()

def get_tenant_id(user_id: int) -> str:
    """The user's tenant id, the key of their chunks in the vector store. LookupError for no such user."""
    conn = _get_connection()
    row = conn.execute("SELECT tenant_id FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if row is None or not row["tenant_id"]:
        raise LookupError(f"No user with id {user_id}")
    return row["tenant_id"]


def get_document_owners() -> List[Dict[str, Any]]:
    """Every document record with its owner's tenant id:
    {user_id, tenant_id, document_id, filename, status, uploaded_at}."""
    conn = _get_connection()
    rows = conn.execute(
        "SELECT u.id AS user_id, u.tenant_id, d.id AS document_id, d.filename, d.status, d.uploaded_at "
        "FROM documents d JOIN users u ON u.id = d.user_id ORDER BY d.id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ── Refresh tokens (Sprint 8, item 4) ─────────────────────────────────────────
#
# Times here are UTC ISO strings, so they compare as text. A token's own expiry is also checked
# when it is decoded; the stored one lets expired rows be cleared away.

def _utc(moment: Optional[datetime] = None) -> str:
    return (moment or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()


def record_refresh_token(user_id: int, jti: str, expires: datetime) -> None:
    """Record a refresh token just issued, and clear away every one that has expired."""
    with _db_lock:
        conn = _get_connection()
        try:
            now = _utc()
            conn.execute("DELETE FROM refresh_tokens WHERE expires_at < ?", (now,))
            conn.execute("INSERT INTO refresh_tokens (jti, user_id, issued_at, expires_at) VALUES (?, ?, ?, ?)",
                         (jti, user_id, now, _utc(expires)))
            conn.commit()
        finally:
            conn.close()


def refresh_token_is_live(user_id: int, jti: str) -> bool:
    """True when this refresh token was issued to this user and has not been revoked. A token
    issued before tokens were recorded is not listed, so it is refused like a revoked one."""
    conn = _get_connection()
    row = conn.execute("SELECT 1 FROM refresh_tokens WHERE jti = ? AND user_id = ? AND revoked_at IS NULL "
                       "AND expires_at >= ?", (jti, user_id, _utc())).fetchone()
    conn.close()
    return row is not None


def revoke_refresh_token(jti: str) -> bool:
    """Revoke one refresh token (signing out). False when it was not live."""
    with _db_lock:
        conn = _get_connection()
        revoked = conn.execute("UPDATE refresh_tokens SET revoked_at = ? WHERE jti = ? AND revoked_at IS NULL",
                               (_utc(), jti)).rowcount
        conn.commit()
        conn.close()
    return revoked == 1


def revoke_user_refresh_tokens(user_id: int) -> int:
    """Revoke every live refresh token of a user (signing out everywhere). Returns how many."""
    with _db_lock:
        conn = _get_connection()
        revoked = conn.execute("UPDATE refresh_tokens SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                               (_utc(), user_id)).rowcount
        conn.commit()
        conn.close()
    return revoked


# ── Conversation Operations ───────────────────────────────────────────────────

def save_conversation(user_id: int, session_id: str, question: str, answer: str,
                      confidence: float = 0.0, mode: str = "original",
                      sources: Optional[List[Dict[str, Any]]] = None, tool_used: Optional[str] = None):
    """Save a Q&A turn to the database, with the sources and tool shown with the answer. Returns its id."""
    with _db_lock:
        conn = _get_connection()
        cursor = conn.execute(
            "INSERT INTO conversations (user_id, session_id, question, answer, confidence, mode, created_at, "
            "sources, tool_used) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, session_id, question, answer, confidence, mode, datetime.now().isoformat(),
             json.dumps(sources if sources is not None else []), tool_used)
        )
        conn.commit()
        turn_id = cursor.lastrowid
        conn.close()
    return turn_id


def get_sessions(user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    """A user's conversations, most recently used first: the session id, its title (the name the
    user gave it, else its first question), how many turns it has, and when it started and was
    last used."""
    conn = _get_connection()
    rows = conn.execute(
        "SELECT session_id, COUNT(*) AS turns, MIN(created_at) AS started_at, MAX(created_at) AS updated_at, "
        "COALESCE((SELECT title FROM session_titles t WHERE t.user_id = c.user_id AND t.session_id = c.session_id), "
        " (SELECT question FROM conversations f WHERE f.user_id = c.user_id AND f.session_id = c.session_id "
        "  ORDER BY f.id LIMIT 1)) AS title "
        "FROM conversations c WHERE user_id = ? GROUP BY session_id ORDER BY MAX(id) DESC LIMIT ?",
        (user_id, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_session_turns(user_id: int, session_id: str) -> List[Dict[str, Any]]:
    """Every turn of one of a user's conversations, oldest first."""
    conn = _get_connection()
    rows = conn.execute(
        "SELECT id, question, answer, confidence, mode, sources, tool_used, feedback, created_at "
        "FROM conversations WHERE user_id = ? AND session_id = ? ORDER BY id",
        (user_id, session_id)
    ).fetchall()
    conn.close()
    return [{**dict(r), "sources": json.loads(r["sources"]) if r["sources"] else []} for r in rows]


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


def clear_conversation(user_id: int, session_id: str) -> int:
    """Delete all conversation history for a session, and the name given to it. Returns how many
    turns were deleted (0 when the user has no such conversation)."""
    with _db_lock:
        conn = _get_connection()
        deleted = conn.execute("DELETE FROM conversations WHERE user_id = ? AND session_id = ?",
                               (user_id, session_id)).rowcount
        conn.execute("DELETE FROM session_titles WHERE user_id = ? AND session_id = ?", (user_id, session_id))
        # A deleted conversation is no longer shared: its link stops working with it
        conn.execute("DELETE FROM shared_sessions WHERE user_id = ? AND session_id = ?", (user_id, session_id))
        conn.commit()
        conn.close()
    return deleted


# ── Sharing a conversation: a link anyone can read it by ──────────────────────

def share_session(user_id: int, session_id: str) -> Optional[str]:
    """The token of the link that shares one of a user's conversations, made now if it is not
    shared yet. None when they have no conversation of that id."""
    with _db_lock:
        conn = _get_connection()
        try:
            if conn.execute("SELECT 1 FROM conversations WHERE user_id = ? AND session_id = ? LIMIT 1",
                            (user_id, session_id)).fetchone() is None:
                return None
            row = conn.execute("SELECT token FROM shared_sessions WHERE user_id = ? AND session_id = ?",
                               (user_id, session_id)).fetchone()
            if row:
                return row["token"]
            token = secrets.token_urlsafe(24)  # 192 random bits: the link cannot be guessed
            conn.execute("INSERT INTO shared_sessions (token, user_id, session_id, created_at) VALUES (?, ?, ?, ?)",
                         (token, user_id, session_id, datetime.now().isoformat()))
            conn.commit()
            return token
        finally:
            conn.close()


def get_share_token(user_id: int, session_id: str) -> Optional[str]:
    """The token one of a user's conversations is shared by, or None when it is not shared."""
    conn = _get_connection()
    row = conn.execute("SELECT token FROM shared_sessions WHERE user_id = ? AND session_id = ?",
                       (user_id, session_id)).fetchone()
    conn.close()
    return row["token"] if row else None


def stop_sharing(user_id: int, session_id: str) -> bool:
    """Stop sharing one of a user's conversations. False when it was not shared."""
    with _db_lock:
        conn = _get_connection()
        stopped = conn.execute("DELETE FROM shared_sessions WHERE user_id = ? AND session_id = ?",
                               (user_id, session_id)).rowcount
        conn.commit()
        conn.close()
    return bool(stopped)


def get_shared_session(token: str) -> Optional[Dict[str, Any]]:
    """Whose conversation a share token opens: {user_id, session_id, title}, or None for a token
    that was never issued or has been withdrawn."""
    conn = _get_connection()
    row = conn.execute(
        "SELECT s.user_id, s.session_id, "
        "COALESCE((SELECT title FROM session_titles t WHERE t.user_id = s.user_id AND t.session_id = s.session_id), "
        " (SELECT question FROM conversations f WHERE f.user_id = s.user_id AND f.session_id = s.session_id "
        "  ORDER BY f.id LIMIT 1)) AS title "
        "FROM shared_sessions s WHERE s.token = ?",
        (token,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def rename_session(user_id: int, session_id: str, title: str) -> bool:
    """Name one of a user's conversations. False when they have no conversation of that id."""
    with _db_lock:
        conn = _get_connection()
        try:
            if conn.execute("SELECT 1 FROM conversations WHERE user_id = ? AND session_id = ? LIMIT 1",
                            (user_id, session_id)).fetchone() is None:
                return False
            conn.execute("INSERT OR REPLACE INTO session_titles (user_id, session_id, title) VALUES (?, ?, ?)",
                         (user_id, session_id, title))
            conn.commit()
            return True
        finally:
            conn.close()


def update_conversation_feedback(user_id: int, turn_id: int, feedback: int) -> bool:
    """Set the feedback (1 up, -1 down, 0 none) on one of a user's turns. False when they have no such turn."""
    with _db_lock:
        conn = _get_connection()
        updated = conn.execute("UPDATE conversations SET feedback = ? WHERE id = ? AND user_id = ?",
                               (feedback, turn_id, user_id)).rowcount
        conn.commit()
        conn.close()
    return updated == 1


def get_turns_rated(feedback: int) -> List[Dict[str, Any]]:
    """Every user's turns with this rating (-1: not helpful), oldest first, with what was shown:
    for the evaluation's candidate questions (src/evaluation/export_feedback.py)."""
    conn = _get_connection()
    rows = conn.execute(
        "SELECT id, question, answer, mode, sources, created_at FROM conversations WHERE feedback = ? ORDER BY id",
        (feedback,)
    ).fetchall()
    conn.close()
    return [{**dict(r), "sources": json.loads(r["sources"]) if r["sources"] else []} for r in rows]


# ── Document Operations ───────────────────────────────────────────────────────

# The columns a document's record is reported with
DOCUMENT_COLUMNS = "id, filename, file_hash, pages, chunks, size_bytes, uploaded_at, status, error"


def save_document_record(user_id: int, filename: str, pages: int, chunks: int,
                         size_bytes: int = 0, file_hash: str = None, status: str = "ready") -> int:
    """Record a document upload in the database. Returns the document's id."""
    with _db_lock:
        conn = _get_connection()
        cursor = conn.execute(
            "INSERT INTO documents (user_id, filename, file_hash, pages, chunks, size_bytes, uploaded_at, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, filename, file_hash, pages, chunks, size_bytes, datetime.now().isoformat(), status)
        )
        conn.commit()
        document_id = cursor.lastrowid
        conn.close()
    return document_id


def set_document_status(user_id: int, document_id: int, status: str, error: Optional[str] = None,
                        pages: int = 0, chunks: int = 0) -> bool:
    """Record how reading a document ended: "ready" with its counts, or "failed" with a message for
    the user. False when the record is gone (the user removed the document meanwhile)."""
    with _db_lock:
        conn = _get_connection()
        updated = conn.execute(
            "UPDATE documents SET status = ?, error = ?, pages = ?, chunks = ? WHERE id = ? AND user_id = ?",
            (status, error, pages, chunks, document_id, user_id)).rowcount
        conn.commit()
        conn.close()
    return updated == 1


def fail_processing_documents(error: str) -> List[Dict[str, Any]]:
    """Mark every document still "processing" as failed, as after a restart cut its reading short.
    Returns {user_id, document_id, filename} for each, so their stored chunks can be removed."""
    with _db_lock:
        conn = _get_connection()
        rows = [dict(r) for r in conn.execute(
            "SELECT user_id, id AS document_id, filename FROM documents WHERE status = 'processing'").fetchall()]
        conn.execute("UPDATE documents SET status = 'failed', error = ? WHERE status = 'processing'", (error,))
        conn.commit()
        conn.close()
    return rows


def get_document(user_id: int, document_id: int) -> Optional[Dict[str, Any]]:
    """One of this user's documents, or None (also None for another user's document)."""
    conn = _get_connection()
    row = conn.execute(f"SELECT {DOCUMENT_COLUMNS} FROM documents WHERE id = ? AND user_id = ?",
                       (document_id, user_id)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_document_record(user_id: int, document_id: int):
    with _db_lock:
        conn = _get_connection()
        conn.execute("DELETE FROM documents WHERE id = ? AND user_id = ?", (document_id, user_id))
        conn.commit()
        conn.close()


def check_duplicate_document(user_id: int, file_hash: str) -> Optional[Dict[str, Any]]:
    """The user's document with the same hash, as {"id", "filename", "status"}, or None.
    A failed upload does not count: the same file may be tried again."""
    conn = _get_connection()
    row = conn.execute(
        "SELECT id, filename, status FROM documents WHERE user_id = ? AND file_hash = ? AND status != 'failed' LIMIT 1",
        (user_id, file_hash)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_documents_detailed(user_id: int) -> List[Dict[str, Any]]:
    """Retrieve detailed metadata of all uploaded documents for a specific user."""
    conn = _get_connection()
    rows = conn.execute(
        f"SELECT {DOCUMENT_COLUMNS} FROM documents WHERE user_id = ? ORDER BY id DESC",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def clear_user_documents(user_id: int):
    with _db_lock:
        conn = _get_connection()
        conn.execute("DELETE FROM documents WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()

