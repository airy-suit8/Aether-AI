"""
memory/conversation.py — conversation memory (Task 4), backed by SQLite.

Each user's sessions are kept apart by a (user_id, session_id) key. The last
settings.memory_max_turns turns of the SESSIONS_KEPT most recently used sessions are cached;
every turn is also saved to the database, so conversations survive a restart and a session that
left the cache is read back from it.
"""

from collections import OrderedDict
from typing import Any, Dict, List, Optional

from src.core.config import settings
from src.db.database import (
    clear_conversation as db_clear_conversation,
    get_conversation_history,
    save_conversation,
)

# What format_history() returns for a session with no turns yet
NO_HISTORY = "(No previous conversation)"

# How many sessions the cache holds. It held every session it ever saw (R10).
SESSIONS_KEPT = 1000


class ConversationMemory:
    """
    Conversation buffer — backed by SQLite for persistence.
    In-memory cache is kept for fast reads during a session.
    Every turn is also saved to disk so conversations survive server restarts.
    """

    def __init__(self):
        self._cache: "OrderedDict[str, List[Dict[str, str]]]" = OrderedDict()

    @staticmethod
    def _cache_key(user_id: int, session_id: str) -> str:
        """Composite key prevents cross-tenant data leaks when session IDs collide."""
        return f"{user_id}:{session_id}"

    def _cached(self, user_id: int, session_id: str) -> List[Dict[str, str]]:
        """The session's cached turns, read from the database when it is not cached; the least
        recently used session leaves the cache once it holds more than SESSIONS_KEPT."""
        key = self._cache_key(user_id, session_id)
        if key in self._cache:
            self._cache.move_to_end(key)
        else:
            self._cache[key] = get_conversation_history(user_id, session_id, limit=settings.memory_max_turns)
            while len(self._cache) > SESSIONS_KEPT:
                self._cache.popitem(last=False)
        return self._cache[key]

    def get_history(self, user_id: int, session_id: str) -> List[Dict[str, str]]:
        """Return list of {"question": ..., "answer": ...} for this session."""
        return self._cached(user_id, session_id)

    def add_turn(self, user_id: int, session_id: str, question: str, answer: str, confidence: float = 0.0,
                 mode: str = "original", sources: Optional[List[Dict[str, Any]]] = None, tool_used: Optional[str] = None):
        """Append a Q&A turn to both cache and SQLite (with the sources and tool shown with the answer).
        Returns the turn's id, the turn_id the client rates it by."""
        key = self._cache_key(user_id, session_id)
        turns = self._cached(user_id, session_id)
        turns.append({"question": question, "answer": answer})
        # Trim cache
        if len(turns) > settings.memory_max_turns:
            self._cache[key] = turns[-settings.memory_max_turns:]
        # Persist to SQLite
        return save_conversation(user_id, session_id, question, answer, confidence, mode, sources, tool_used)

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
