"""Conversation memory (Task 4): SQLite-backed history with a per-user, per-session cache."""

import uuid

import pytest

from src.db import database
from src.pipeline import rag
from src.core.config import settings
from src.memory import conversation
from src.memory.conversation import ConversationMemory


@pytest.fixture
def user_id():
    return database.create_user(f"mem_{uuid.uuid4().hex[:8]}", "hash")


def test_empty_history(user_id):
    memory = ConversationMemory()
    assert memory.get_history(user_id, "s") == []
    assert memory.format_history(user_id, "s") == "(No previous conversation)"


def test_turns_are_kept_in_order_and_formatted(user_id):
    memory = ConversationMemory()
    memory.add_turn(user_id, "s", "Who inspects the blades?", "The Orion team.")
    memory.add_turn(user_id, "s", "How often?", "Every 90 days.")
    assert memory.get_history(user_id, "s") == [
        {"question": "Who inspects the blades?", "answer": "The Orion team."},
        {"question": "How often?", "answer": "Every 90 days."},
    ]
    assert memory.format_history(user_id, "s") == (
        "User: Who inspects the blades?\nAssistant: The Orion team.\n"
        "User: How often?\nAssistant: Every 90 days."
    )


def test_turns_survive_a_restart_with_confidence_and_mode(user_id):
    ConversationMemory().add_turn(user_id, "s", "q1", "a1", confidence=0.72, mode="hybrid")
    assert ConversationMemory().get_history(user_id, "s") == [{"question": "q1", "answer": "a1"}]
    conn = database._get_connection()
    row = conn.execute("SELECT confidence, mode FROM conversations WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    assert (row["confidence"], row["mode"]) == (0.72, "hybrid")


def test_history_is_capped_at_the_most_recent_turns(user_id):
    memory = ConversationMemory()
    for i in range(settings.memory_max_turns + 3):
        memory.add_turn(user_id, "s", f"q{i}", f"a{i}")
    expected = [f"q{i}" for i in range(3, settings.memory_max_turns + 3)]
    assert [t["question"] for t in memory.get_history(user_id, "s")] == expected
    # A fresh process loads the same window from the database
    assert [t["question"] for t in ConversationMemory().get_history(user_id, "s")] == expected


def test_sessions_and_users_are_kept_apart(user_id):
    other = database.create_user(f"mem_{uuid.uuid4().hex[:8]}", "hash")
    memory = ConversationMemory()
    memory.add_turn(user_id, "s1", "mine", "a")
    assert memory.get_history(user_id, "s2") == []
    assert memory.get_history(other, "s1") == []


def test_clear_session_empties_cache_and_database(user_id):
    memory = ConversationMemory()
    memory.add_turn(user_id, "s", "q", "a")
    memory.add_turn(user_id, "keep", "q", "a")
    memory.clear_session(user_id, "s")
    assert memory.get_history(user_id, "s") == []
    assert ConversationMemory().get_history(user_id, "s") == []
    assert len(memory.get_history(user_id, "keep")) == 1


def test_module_helpers_use_the_shared_memory(user_id):
    conversation.memory.add_turn(user_id, "helper", "q", "a")
    assert conversation.get_session_history(user_id, "helper") == [{"question": "q", "answer": "a"}]
    conversation.clear_session(user_id, "helper")
    assert conversation.get_session_history(user_id, "helper") == []


# ── Memory in the pipeline: a follow-up question is rewritten using the history ──

@pytest.mark.parametrize("ask", [
    lambda u, q: rag.answer(u, q, session_id="follow"),
    lambda u, q: list(rag.events(u, q, session_id="follow")),
    lambda u, q: rag.answer(u, q, session_id="follow", mode="hybrid"),
    lambda u, q: rag.answer(u, q, session_id="follow", mode="langchain"),
], ids=["answer", "events", "hybrid", "langchain"])
def test_follow_up_is_rewritten_with_the_history(user_id, fake_llm, ask):
    conversation.memory.add_turn(user_id, "follow", "Who maintains the Zephyr turbine?", "The Orion field team.")
    ask(user_id, "How often do they do it?")
    rewrite = [p for p in fake_llm.prompts if "Standalone Question:" in p]
    assert len(rewrite) == 1
    assert "User: Who maintains the Zephyr turbine?" in rewrite[0]
    assert "Current Question: How often do they do it?" in rewrite[0]


def test_first_question_is_not_rewritten(user_id, fake_llm):
    rag.answer(user_id, "How often?", session_id="first")
    assert not any("Standalone Question:" in p for p in fake_llm.prompts)


def test_the_cache_keeps_only_the_most_recently_used_sessions(user_id, monkeypatch):
    # R10 (first audit): the cache held every session it ever saw, for as long as the server ran
    monkeypatch.setattr(conversation, "SESSIONS_KEPT", 3)
    memory = ConversationMemory()
    for n in range(5):
        memory.add_turn(user_id, f"s{n}", f"question {n}", f"answer {n}")
    memory.get_history(user_id, "s2")  # used again: it stays
    memory.add_turn(user_id, "s5", "question 5", "answer 5")
    assert list(memory._cache) == [f"{user_id}:s4", f"{user_id}:s2", f"{user_id}:s5"]
    # A session that left the cache is read back from the database, whole
    assert memory.get_history(user_id, "s0") == [{"question": "question 0", "answer": "answer 0"}]
    assert len(memory._cache) == 3

