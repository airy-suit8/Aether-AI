"""
Tenant isolation in both directions (S2): neither user can list, search, delete, read the
history of, or leave feedback on the other's data, even when both use the same session id.

Each test runs twice, once with Alice as the owner and Bob as the other user, then reversed.
"""

import jwt
import pytest

from src.db import database
import rag_engine
from helpers import DOC_TEXT, upload_text, ask, ask_stream

ALICE_DOC = ("zephyr_manual.txt", DOC_TEXT, "How often is the Zephyr turbine blade inspection?", "90 days")
BOB_DOC = (
    "borealis_notes.txt",
    "The Borealis reactor coolant must be replaced every 45 days by the Vega crew.",
    "How often is the Borealis reactor coolant replaced?",
    "45 days",
)

MODES = [{}, {"use_hybrid": True}, {"use_langchain": True}, {"use_agent": True}]
MODE_IDS = ["default", "hybrid", "langchain", "agent"]
SHARED = "shared-session"


def _user_id(headers):
    return int(jwt.decode(headers["Authorization"].split()[1], options={"verify_signature": False})["sub"])


def _rows(user_id, session_id):
    conn = database._get_connection()
    rows = conn.execute(
        "SELECT question, feedback FROM conversations WHERE user_id = ? AND session_id = ? ORDER BY id",
        (user_id, session_id),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _chunks_of(user_id):
    return rag_engine._store.chroma._collection.get(where={"user_id": user_id}, include=[])["ids"]


@pytest.fixture(params=["alice_owns", "bob_owns"])
def tenants(request, client, make_user):
    """Two users who each uploaded one document. Returns (owner, other) as dicts."""
    _, alice = make_user("alice")
    _, bob = make_user("bob")
    a = {"headers": alice, "id": _user_id(alice), "doc": ALICE_DOC}
    b = {"headers": bob, "id": _user_id(bob), "doc": BOB_DOC}
    for t in (a, b):
        filename, text, _, _ = t["doc"]
        assert upload_text(client, t["headers"], filename=filename, text=text).status_code == 200
    return (a, b) if request.param == "alice_owns" else (b, a)


def test_document_lists_are_separate(client, tenants):
    owner, other = tenants
    owner_file, other_file = owner["doc"][0], other["doc"][0]
    assert client.get("/api/v1/documents", headers=other["headers"]).json()["documents"] == [other_file]
    detailed = client.get("/api/v1/documents/detailed", headers=other["headers"]).json()["documents"]
    assert [d["filename"] for d in detailed] == [other_file]
    assert owner_file not in str(detailed)


@pytest.mark.parametrize("modes", MODES, ids=MODE_IDS)
def test_search_never_returns_the_other_users_chunks(client, tenants, modes):
    owner, other = tenants
    owner_file, _, owner_question, owner_fact = owner["doc"]

    r = ask(client, other["headers"], owner_question, session_id="probe", **modes)
    assert r.status_code == 200, r.text
    assert owner_file not in [s["source"] for s in r.json()["sources"]]
    assert owner_fact not in r.json()["answer"]

    status, events = ask_stream(client, other["headers"], owner_question, session_id="probe-stream", **modes)
    assert status == 200 and events[-1]["type"] == "done"
    assert owner_file not in [s["source"] for s in events[-1]["sources"]]
    assert owner_fact not in "".join(e.get("content", "") for e in events)


def test_store_searches_are_filtered_by_user(tenants):
    owner, other = tenants
    owner_file, owner_text, owner_question, _ = owner["doc"]
    store = rag_engine._store
    # Query with the owner's exact text: the strongest possible match for the owner's chunk
    for search in (store.search, store.search_bm25, store.search_hybrid):
        for query in (owner_text, owner_question):
            hits = search(other["id"], query, k=10)
            assert all(h["meta"]["user_id"] == other["id"] for h in hits), search.__name__
            assert owner_file not in [h["meta"]["source"] for h in hits], search.__name__


def test_delete_removes_only_your_own_documents(client, tenants):
    owner, other = tenants
    owner_chunks = _chunks_of(owner["id"])
    assert owner_chunks

    r = client.delete("/api/v1/documents", headers=other["headers"])
    assert r.status_code == 200 and r.json()["deleted"] == 1
    assert _chunks_of(other["id"]) == []

    assert _chunks_of(owner["id"]) == owner_chunks
    assert client.get("/api/v1/documents", headers=owner["headers"]).json()["count"] == 1
    r = ask(client, owner["headers"], owner["doc"][2], session_id="after")
    assert owner["doc"][3] in r.json()["answer"]


@pytest.mark.parametrize("modes", MODES, ids=MODE_IDS)
def test_history_with_the_same_session_id_is_not_shared(client, tenants, fake_llm, modes):
    owner, other = tenants
    # On topic for the owner's document, so it is answered (a refused question saves no turn)
    secret_question = f"{owner['doc'][2]} Private note {owner['id']}."
    assert ask(client, owner["headers"], secret_question, session_id=SHARED, **modes).status_code == 200
    assert len(_rows(owner["id"], SHARED)) == 1

    # The other user's history for the same session id is empty, in memory and on disk
    assert rag_engine._memory.get_history(other["id"], SHARED) == []
    assert _rows(other["id"], SHARED) == []

    # and nothing of the owner's turn reaches the model when the other user asks
    fake_llm.prompts.clear()
    assert ask(client, other["headers"], other["doc"][2], session_id=SHARED, **modes).status_code == 200
    assert fake_llm.prompts, "the other user's question reached no model"
    assert not any(secret_question in p for p in fake_llm.prompts)
    assert [r["question"] for r in _rows(other["id"], SHARED)] == [other["doc"][2]]
    assert [r["question"] for r in _rows(owner["id"], SHARED)] == [secret_question]


def test_feedback_lands_only_on_your_own_turn(client, tenants):
    owner, other = tenants
    ask(client, owner["headers"], owner["doc"][2], session_id=SHARED)

    # The other user has no turn in this session: feedback must not touch the owner's turn
    r = client.post("/api/v1/feedback", headers=other["headers"], json={"session_id": SHARED, "feedback": -1})
    assert r.status_code == 200
    assert _rows(owner["id"], SHARED)[0]["feedback"] == 0

    # Once both have a turn, each one's feedback lands on their own
    ask(client, other["headers"], other["doc"][2], session_id=SHARED)
    client.post("/api/v1/feedback", headers=owner["headers"], json={"session_id": SHARED, "feedback": 1})
    client.post("/api/v1/feedback", headers=other["headers"], json={"session_id": SHARED, "feedback": -1})
    assert _rows(owner["id"], SHARED)[0]["feedback"] == 1
    assert _rows(other["id"], SHARED)[0]["feedback"] == -1


def test_clearing_a_session_clears_only_your_own_history(client, tenants):
    owner, other = tenants
    ask(client, owner["headers"], owner["doc"][2], session_id=SHARED)
    ask(client, other["headers"], other["doc"][2], session_id=SHARED)

    r = client.post("/api/v1/session/clear", headers=other["headers"], json={"question": "", "session_id": SHARED})
    assert r.status_code == 200
    assert _rows(other["id"], SHARED) == []
    assert len(_rows(owner["id"], SHARED)) == 1
    assert len(rag_engine._memory.get_history(owner["id"], SHARED)) == 1
