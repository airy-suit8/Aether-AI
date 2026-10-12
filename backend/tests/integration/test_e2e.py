"""
End-to-end: register -> log in -> upload -> ask in every mode -> cited answer -> saved turn
-> feedback -> tenant isolation -> duplicate rejected -> delete (T1, T2).

Runs entirely through the HTTP API with fake embeddings, a scripted fake chat model,
a temp database and a temp vector store (see conftest.py). No API key, no network.
"""

import jwt
import pytest

from src.db import database
from helpers import DOC_TEXT, upload_text, ask, ask_stream

FILENAME = "zephyr_manual.txt"
QUESTION = "How often is the Zephyr turbine blade inspection?"

MODES = {
    "default": ({}, "original"),
    "hybrid": ({"mode": "hybrid"}, "hybrid"),
    "agent": ({"mode": "agent"}, "agent"),
    "langchain": ({"mode": "langchain"}, "langchain"),
}


def _user_id(headers):
    return int(jwt.decode(headers["Authorization"].split()[1], options={"verify_signature": False})["sub"])


def _turns(user_id, session_id):
    conn = database._get_connection()
    rows = conn.execute(
        "SELECT question, answer, confidence, mode, feedback FROM conversations "
        "WHERE user_id = ? AND session_id = ? ORDER BY id",
        (user_id, session_id),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _assert_cites_the_file(sources):
    assert sources, "the answer has no sources"
    cited = [s for s in sources if s["source"] == FILENAME]
    assert cited, sources
    assert "blade inspection every 90 days" in cited[0]["snippet"]
    assert cited[0]["page"] == 1
    assert 0 < cited[0]["score"] <= 1


def test_end_to_end(client, make_user):
    # ── Register and log in two users (make_user does both over HTTP) ──────────
    _, alice = make_user("alice")
    _, bob = make_user("bob")
    alice_id = _user_id(alice)

    # ── Alice uploads a small text file ─────────────────────────────────────────
    up = upload_text(client, alice, filename=FILENAME, text=DOC_TEXT)
    assert up.status_code == 200, up.text
    assert up.json()["filename"] == FILENAME
    chunks = up.json()["chunks"]
    assert chunks >= 1

    listed = client.get("/api/v1/documents", headers=alice).json()
    assert listed == {"documents": [FILENAME], "count": 1}
    detailed = client.get("/api/v1/documents/detailed", headers=alice).json()["documents"][0]
    assert detailed["filename"] == FILENAME and detailed["chunks"] == chunks
    assert detailed["size_bytes"] == len(DOC_TEXT.encode()) and detailed["uploaded_at"]

    # ── Ask in every mode, non-streaming and streaming ─────────────────────────
    for name, (flags, stored_mode) in MODES.items():
        session = f"e2e-{name}"
        r = ask(client, alice, QUESTION, session_id=session, **flags)
        assert r.status_code == 200, (name, r.text)
        body = r.json()
        assert "90 days" in body["answer"], (name, body["answer"])
        _assert_cites_the_file(body["sources"])
        assert body["confidence"] > 0

        status, events = ask_stream(client, alice, QUESTION, session_id=session + "-stream", **flags)
        assert status == 200
        assert events[-1]["type"] == "done", (name, events)
        assert "90 days" in "".join(e["content"] for e in events if e["type"] == "token")
        _assert_cites_the_file(events[-1]["sources"])

        # One saved turn per question, with the real confidence and the right mode
        for sid in (session, session + "-stream"):
            turns = _turns(alice_id, sid)
            assert len(turns) == 1, (name, sid, turns)
            assert turns[0]["question"] == QUESTION
            assert turns[0]["mode"] == stored_mode
            assert turns[0]["confidence"] > 0

    # ── Feedback lands on the latest turn; clearing the session removes it ─────
    assert client.post("/api/v1/feedback", headers=alice,
                       json={"session_id": "e2e-default", "feedback": 1}).status_code == 200
    assert _turns(alice_id, "e2e-default")[0]["feedback"] == 1
    cleared = client.post("/api/v1/session/clear", headers=alice, json={"question": "", "session_id": "e2e-default"})
    assert cleared.status_code == 200
    assert _turns(alice_id, "e2e-default") == []

    # ── Bob cannot see, search or delete Alice's document ──────────────────────
    assert client.get("/api/v1/documents", headers=bob).json()["count"] == 0
    assert client.get("/api/v1/documents/detailed", headers=bob).json()["count"] == 0
    for name, (flags, _) in MODES.items():
        r = ask(client, bob, QUESTION, session_id=f"bob-{name}", **flags)
        assert r.status_code == 200, (name, r.text)
        assert r.json()["sources"] == [], name
        assert "90 days" not in r.json()["answer"], name
    assert client.delete("/api/v1/documents", headers=bob).json()["deleted"] == 0
    assert client.get("/api/v1/documents", headers=alice).json()["count"] == 1

    # ── Uploading the same file again is rejected ──────────────────────────────
    again = upload_text(client, alice, filename=FILENAME, text=DOC_TEXT)
    assert again.status_code == 409

    # ── Delete reports the real number of chunks, and the document is gone ─────
    deleted = client.delete("/api/v1/documents", headers=alice)
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] == chunks
    assert client.get("/api/v1/documents", headers=alice).json()["count"] == 0
    after = ask(client, alice, QUESTION, session_id="after-delete").json()
    assert after["sources"] == []


@pytest.mark.parametrize("path,method", [
    ("/api/v1/upload", "post"), ("/api/v1/chat", "post"), ("/api/v1/chat/stream", "post"),
    ("/api/v1/feedback", "post"), ("/api/v1/session/clear", "post"),
    ("/api/v1/documents", "get"), ("/api/v1/documents/detailed", "get"), ("/api/v1/documents", "delete"),
])
def test_protected_routes_require_a_token(client, path, method):
    assert getattr(client, method)(path).status_code == 401
