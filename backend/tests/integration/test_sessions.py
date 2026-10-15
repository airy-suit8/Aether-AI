"""
Conversations read back (F8, Task 5; Sprint 5 item 7): who is signed in, the list of a user's
conversations, and every turn of one, with the sources and tool that were shown with each
answer, so a reloaded page can show the conversation again.
"""

import pytest

from helpers import ask, ask_stream, upload_text
from src.core.config import settings

QUESTION = "How often is the Zephyr turbine blade inspection?"


def test_me_names_the_signed_in_user(client, make_user):
    username, headers = make_user("Me_Case")
    r = client.get("/api/v1/auth/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["username"] == username  # as registered, case kept
    assert r.json()["created_at"] and set(r.json()) == {"username", "created_at"}
    assert client.get("/api/v1/auth/me").status_code == 401


def test_sessions_are_listed_most_recent_first_and_titled_by_their_first_question(client, make_user):
    _, headers = make_user("sessions")
    upload_text(client, headers)
    ask(client, headers, QUESTION, session_id="first")
    ask(client, headers, "Who logs the Zephyr inspection?", session_id="second")
    ask(client, headers, "The Zephyr turbine blade inspection schedule", session_id="first")  # first is used last

    sessions = client.get("/api/v1/sessions", headers=headers).json()["sessions"]
    assert [(s["session_id"], s["title"], s["turns"]) for s in sessions] == [
        ("first", QUESTION, 2),
        ("second", "Who logs the Zephyr inspection?", 1),
    ]
    assert all(s["started_at"] <= s["updated_at"] for s in sessions)
    assert [s["session_id"] for s in client.get("/api/v1/sessions?limit=1", headers=headers).json()["sessions"]] == ["first"]


@pytest.mark.parametrize("streaming", [False, True])
def test_a_session_s_turns_come_back_with_what_was_shown(client, make_user, streaming):
    _, headers = make_user("turns")
    upload_text(client, headers)
    if streaming:
        _, events = ask_stream(client, headers, QUESTION, session_id="s")
        shown = events[-1]
        answer = "".join(e["content"] for e in events if e["type"] == "token")
    else:
        shown = ask(client, headers, QUESTION, session_id="s").json()
        answer = shown["answer"]
    ask(client, headers, QUESTION, session_id="s", mode="agent")

    r = client.get("/api/v1/sessions/s/messages", headers=headers)
    assert r.status_code == 200 and r.json()["session_id"] == "s"
    first, second = r.json()["turns"]
    assert first["question"] == QUESTION and first["answer"] == answer
    assert first["sources"] == shown["sources"] and first["sources"]
    assert first["confidence"] == shown["confidence"] and first["mode"] == "original"
    assert first["tool_used"] is None and first["feedback"] == 0 and isinstance(first["turn_id"], int)
    assert second["mode"] == "agent" and second["tool_used"] == "document_search" and second["sources"]
    assert first["turn_id"] < second["turn_id"]


def test_another_user_s_sessions_are_neither_listed_nor_readable(client, make_user):
    _, alice = make_user("sess_a")
    _, bob = make_user("sess_b")
    upload_text(client, alice)
    ask(client, alice, QUESTION, session_id="shared-name")
    assert client.get("/api/v1/sessions", headers=bob).json() == {"sessions": []}
    assert client.get("/api/v1/sessions/shared-name/messages", headers=bob).json() == {
        "session_id": "shared-name", "turns": [], "grounded_at": settings.grounded_line()}


@pytest.mark.parametrize("session_id", ["has space", "semi;colon", "x" * 101])
def test_a_bad_session_id_is_a_422(client, make_user, session_id):
    _, headers = make_user("sess_bad")
    assert client.get(f"/api/v1/sessions/{session_id}/messages", headers=headers).status_code == 422


def test_reading_conversations_needs_a_token(client):
    assert client.get("/api/v1/sessions").status_code == 401
    assert client.get("/api/v1/sessions/s/messages").status_code == 401


# ── Renaming and deleting a conversation (Sprint 8, item 3) ──────────────────

def _titles(client, headers):
    return {s["session_id"]: s["title"] for s in client.get("/api/v1/sessions", headers=headers).json()["sessions"]}


def test_a_conversation_can_be_renamed_and_keeps_its_turns(client, make_user):
    _, headers = make_user("rename")
    upload_text(client, headers)
    ask(client, headers, QUESTION, session_id="named")
    ask(client, headers, "Who logs the Zephyr inspection?", session_id="other")

    r = client.patch("/api/v1/sessions/named", headers=headers, json={"title": "  Blade\n inspections  "})
    assert r.status_code == 200, r.text
    assert r.json() == {"session_id": "named", "title": "Blade inspections"}
    assert _titles(client, headers) == {"named": "Blade inspections", "other": "Who logs the Zephyr inspection?"}
    turns = client.get("/api/v1/sessions/named/messages", headers=headers).json()["turns"]
    assert [t["question"] for t in turns] == [QUESTION]

    # Renamed again, the latest name wins
    client.patch("/api/v1/sessions/named", headers=headers, json={"title": "Inspections"})
    assert _titles(client, headers)["named"] == "Inspections"


@pytest.mark.parametrize("body", [{"title": ""}, {"title": "   "}, {"title": "x" * 201}, {}, {"title": "ok", "extra": 1}])
def test_a_name_must_be_one_to_200_characters(client, make_user, body):
    _, headers = make_user("renamebad")
    upload_text(client, headers)
    ask(client, headers, QUESTION, session_id="s")
    assert client.patch("/api/v1/sessions/s", headers=headers, json=body).status_code == 422


def test_a_conversation_is_deleted_with_its_name_and_its_memory(client, make_user, fake_llm):
    _, headers = make_user("deleteconv")
    upload_text(client, headers)
    ask(client, headers, QUESTION, session_id="gone")
    client.patch("/api/v1/sessions/gone", headers=headers, json={"title": "To be deleted"})
    ask(client, headers, "Who logs the Zephyr inspection?", session_id="kept")

    r = client.delete("/api/v1/sessions/gone", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"message": "Conversation deleted", "session_id": "gone"}
    assert set(_titles(client, headers)) == {"kept"}
    assert client.get("/api/v1/sessions/gone/messages", headers=headers).json()["turns"] == []
    assert client.delete("/api/v1/sessions/gone", headers=headers).status_code == 404  # already gone

    # Asked again under the same id, it starts afresh: no history to rewrite against, no old name
    fake_llm.prompts.clear()
    ask(client, headers, QUESTION, session_id="gone")
    assert not any("Standalone Question:" in p for p in fake_llm.prompts)
    assert _titles(client, headers)["gone"] == QUESTION


def test_another_user_s_conversation_can_be_neither_renamed_nor_deleted(client, make_user):
    _, owner = make_user("convowner")
    _, other = make_user("convother")
    upload_text(client, owner)
    ask(client, owner, QUESTION, session_id="mine")

    assert client.patch("/api/v1/sessions/mine", headers=other, json={"title": "Taken"}).status_code == 404
    assert client.delete("/api/v1/sessions/mine", headers=other).status_code == 404
    assert _titles(client, owner) == {"mine": QUESTION}
    # A conversation with no turns yet has nothing to rename or delete
    assert client.patch("/api/v1/sessions/empty", headers=owner, json={"title": "New"}).status_code == 404
    assert client.delete("/api/v1/sessions/empty", headers=owner).status_code == 404


def test_renaming_and_deleting_need_a_token_and_a_good_id(client, make_user):
    assert client.patch("/api/v1/sessions/s", json={"title": "x"}).status_code == 401
    assert client.delete("/api/v1/sessions/s").status_code == 401
    _, headers = make_user("convid")
    assert client.patch("/api/v1/sessions/has space", headers=headers, json={"title": "x"}).status_code == 422
    assert client.delete("/api/v1/sessions/" + "x" * 101, headers=headers).status_code == 422
