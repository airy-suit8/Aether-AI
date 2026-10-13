"""
Sharing a conversation: its owner makes a link, anyone who has the link can read that one
conversation without signing in, and the owner can withdraw it.
"""

import re

import pytest

from helpers import ask, upload_text
from src.core.config import settings
from src.core.logging import request_logger

QUESTION = "How often is the Zephyr turbine blade inspection?"


@pytest.fixture
def owner(client, make_user):
    """A user with a document and one answered question in the conversation "talk"."""
    _, headers = make_user("sharer")
    upload_text(client, headers)
    assert ask(client, headers, QUESTION, session_id="talk").json()["turn_id"]
    return headers


def share(client, headers, session_id="talk"):
    return client.post(f"/api/v1/sessions/{session_id}/share", headers=headers)


def read(client, token):
    return client.get(f"/api/v1/shared/{token}")  # no Authorization header: anyone


# ── Making the link, and what it shows ────────────────────────────────────────

def test_a_shared_conversation_can_be_read_by_anyone_with_the_link(client, owner):
    r = share(client, owner)
    assert r.status_code == 200
    token = r.json()["token"]
    assert r.json() == {"session_id": "talk", "token": token}
    assert re.fullmatch(r"[A-Za-z0-9_-]{32}", token)  # 192 random bits

    shared = read(client, token)
    assert shared.status_code == 200
    body = shared.json()
    assert body["title"] == QUESTION and len(body["turns"]) == 1
    turn = body["turns"][0]
    assert turn["question"] == QUESTION and turn["answer"]
    assert turn["sources"] and turn["sources"][0]["source"] == "zephyr_manual.txt"
    # What it does not show: whose it is, the turn's id, the owner's rating
    assert set(body) == {"title", "turns"}
    assert set(turn) == {"question", "answer", "confidence", "mode", "sources", "tool_used", "created_at"}


def test_sharing_again_gives_the_same_link_and_the_owner_can_look_it_up(client, owner):
    session_id = "talk"
    token = share(client, owner).json()["token"]
    assert share(client, owner).json()["token"] == token
    assert client.get(f"/api/v1/sessions/{session_id}/share", headers=owner).json() == {"session_id": "talk", "token": token}


def test_only_the_shared_conversation_is_readable(client, owner):
    ask(client, owner, "Who logs the inspection in the Halcyon register?", session_id="private")
    body = read(client, share(client, owner).json()["token"]).json()
    assert [t["question"] for t in body["turns"]] == [QUESTION]
    assert "Halcyon register?" not in str(body["turns"][0]["question"])
    session_id = "private"
    assert client.get(f"/api/v1/sessions/{session_id}/share", headers=owner).json()["token"] is None


def test_a_shared_conversation_shows_what_is_asked_after_it_was_shared(client, owner):
    token = share(client, owner).json()["token"]
    later = "Which team carries out the Zephyr turbine blade inspection?"
    assert ask(client, owner, later, session_id="talk").json()["turn_id"]
    assert [t["question"] for t in read(client, token).json()["turns"]] == [QUESTION, later]


def test_the_shared_title_is_the_name_the_owner_gave(client, owner):
    session_id = "talk"
    token = share(client, owner).json()["token"]
    client.patch(f"/api/v1/sessions/{session_id}", headers=owner, json={"title": "Blade inspections"})
    assert read(client, token).json()["title"] == "Blade inspections"


# ── Withdrawing it ────────────────────────────────────────────────────────────

def test_a_withdrawn_link_stops_working_and_a_new_one_is_different(client, owner):
    session_id = "talk"
    token = share(client, owner).json()["token"]
    r = client.delete(f"/api/v1/sessions/{session_id}/share", headers=owner)
    assert r.status_code == 200 and r.json() == {"session_id": "talk", "token": None}

    gone = read(client, token)
    assert gone.status_code == 404
    assert gone.json()["detail"] == "This conversation is not shared, or its link was withdrawn."
    assert client.get(f"/api/v1/sessions/{session_id}/share", headers=owner).json()["token"] is None
    assert client.delete(f"/api/v1/sessions/{session_id}/share", headers=owner).status_code == 200  # nothing left to withdraw

    again = share(client, owner).json()["token"]
    assert again != token and read(client, again).status_code == 200 and read(client, token).status_code == 404


def test_deleting_the_conversation_withdraws_its_link(client, owner):
    session_id = "talk"
    token = share(client, owner).json()["token"]
    assert client.delete(f"/api/v1/sessions/{session_id}", headers=owner).status_code == 200
    assert read(client, token).status_code == 404
    # A new conversation that reuses the id is not shared by the old link
    ask(client, owner, QUESTION, session_id="talk")
    assert read(client, token).status_code == 404
    assert client.get(f"/api/v1/sessions/{session_id}/share", headers=owner).json()["token"] is None


# ── Who may share what ────────────────────────────────────────────────────────

def test_another_user_s_conversation_cannot_be_shared_or_looked_up(client, owner, make_user):
    session_id = "talk"
    token = share(client, owner).json()["token"]
    _, stranger = make_user("stranger")
    assert share(client, stranger).status_code == 404
    assert client.get(f"/api/v1/sessions/{session_id}/share", headers=stranger).json()["token"] is None
    # A stranger "withdrawing" it changes nothing for the owner
    assert client.delete(f"/api/v1/sessions/{session_id}/share", headers=stranger).status_code == 200
    assert read(client, token).status_code == 200


def test_a_conversation_with_no_turns_cannot_be_shared(client, make_user):
    _, headers = make_user("empty")
    r = share(client, headers, session_id="nothing-yet")
    assert r.status_code == 404 and r.json()["detail"] == "No such conversation."


@pytest.mark.parametrize("method", ["post", "get", "delete"])
def test_the_owner_s_routes_need_a_sign_in(client, method):
    session_id = "talk"
    assert getattr(client, method)(f"/api/v1/sessions/{session_id}/share").status_code == 401


# ── Links that were never made ────────────────────────────────────────────────

def test_an_unknown_link_is_a_404_and_a_malformed_one_a_422(client):
    assert read(client, "A" * 32).status_code == 404
    assert read(client, "short").status_code == 422
    assert read(client, "not*allowed*characters*in*a*token").status_code == 422
    assert read(client, "A" * 65).status_code == 422


def test_the_link_is_never_written_to_the_log(client, owner):
    token = share(client, owner).json()["token"]
    assert read(client, token).status_code == 200
    for handler in request_logger.handlers:
        handler.flush()
    log = (settings.log_dir / "requests.log").read_text(encoding="utf-8")
    assert "session_shared" in log and "shared_session_read" in log
    assert token not in log
