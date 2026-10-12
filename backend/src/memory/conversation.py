"""
memory/conversation.py — conversation memory (Task 4), backed by SQLite.

Each user's sessions are kept apart by a (user_id, session_id) key. The last
settings.memory_max_turns turns are cached; every turn is also saved to the database, so
conversations survive a restart.
"""

from typing import Any, Dict, List, Optional

from src.core.config import settings
from src.db.database import (
    clear_conversation as db_clear_conversation,
    get_conversation_history,
    save_conversation,
)

# What format_history() returns for a session with no turns yet
NO_HISTORY = "(No previous conversation)"


class ConversationMemory:
    """
    Conversation buffer — backed by SQLite for persistence.
    In-memory cache is kept for fast reads during a session.
    Every turn is also saved to disk so conversations survive server restarts.
    """

    def __init__(self):
        self._cache: Dict[str, List[Dict[str, str]]] = {}

    @staticmethod
    def _cache_key(user_id: int, session_id: str) -> str:
        """Composite key prevents cross-tenant data leaks when session IDs collide."""
        return f"{user_id}:{session_id}"

    def get_history(self, user_id: int, session_id: str) -> List[Dict[str, str]]:
        """Return list of {"question": ..., "answer": ...} for this session."""
        key = self._cache_key(user_id, session_id)
        if key not in self._cache:
            self._cache[key] = get_conversation_history(user_id, session_id, limit=settings.memory_max_turns)
        return self._cache.get(key, [])

    def add_turn(self, user_id: int, session_id: str, question: str, answer: str, confidence: float = 0.0,
                 mode: str = "original", sources: Optional[List[Dict[str, Any]]] = None, tool_used: Optional[str] = None):
        """Append a Q&A turn to both cache and SQLite (with the sources and tool shown with the answer)."""
        key = self._cache_key(user_id, session_id)
        if key not in self._cache:
            self._cache[key] = get_conversation_history(user_id, session_id, limit=settings.memory_max_turns)
        self._cache[key].append({"question": question, "answer": answer})
        # Trim cache
        if len(self._cache[key]) > settings.memory_max_turns:
            self._cache[key] = self._cache[key][-settings.memory_max_turns:]
        # Persist to SQLite
        save_conversation(user_id, session_id, question, answer, confidence, mode, sources, tool_used)

    def clear_session(self, user_id: int, session_id: str):
        """Clear history from both cache and SQLite."""
        key = self._cache_key(user_id, session_id)
        self._cache.pop(key, None)
        db_clear_conversation(user_id, session_id)

    def format_history(self, user_id: int, session_id: str) -> str:
        """Format history into a readable string for the prompt."""
        history = self.get_history(user_id, session_id)
        if not history:
            return NO_HISTORY
        lines = []
        for turn in history:
            lines.append(f"User: {turn['question']}")
            lines.append(f"Assistant: {turn['answer']}")
        return "\n".join(lines)


# Module-level singleton
memory = ConversationMemory()


# ── Session helpers ───────────────────────────────────────────────────────────

def clear_session(user_id: int, session_id: str):
    """Clear conversation memory for a session."""
    memory.clear_session(user_id, session_id)


def get_session_history(user_id: int, session_id: str) -> List[Dict[str, str]]:
    """Return conversation history for a session."""
    return memory.get_history(user_id, session_id)
