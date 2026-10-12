"""
Every API route: success, 401 without a valid token, 422 on bad input, and the declared rate limit.

The end-to-end test already walks the happy path; this file fills in the rest route by route.
Routes with no request body or parameters (health, document list, detailed list, delete) have
no input that could be rejected with a 422.
"""

import uuid
from datetime import timedelta

import jwt
import pytest

from src.api import routes_chat, routes_documents
from src.core import security
from src.core.config import settings
from helpers import DOC_TEXT, upload_text, ask, ask_stream

QUESTION = "How often is the Zephyr turbine blade inspection?"

PROTECTED = [
    ("post", "/api/v1/upload"), ("post", "/api/v1/chat"), ("post", "/api/v1/chat/stream"),
    ("post", "/api/v1/feedback"), ("post", "/api/v1/session/clear"),
    ("get", "/api/v1/documents"), ("get", "/api/v1/documents/detailed"), ("delete", "/api/v1/documents"),
]


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


BAD_TOKENS = {
    "garbage": "not-a-jwt",
    "wrong_secret": jwt.encode({"sub": "1"}, "a-different-secret-that-is-at-least-32-bytes", algorithm="HS256"),
    "no_subject": security.create_access_token({"name": "x"}, expires_delta=timedelta(minutes=5)),
    "expired": security.create_access_token({"sub": "1"}, expires_delta=timedelta(seconds=-10)),
}


# ── Success, one per route ────────────────────────────────────────────────────

def test_health_is_public_and_reports_ok(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert {"total_documents", "total_chunks"} <= body["documents"].keys()
    assert {"total_turns", "total_sessions"} <= body["conversations"].keys()


def test_register_then_login(client):
    r = client.post("/api/v1/auth/register", json={"username": "route_user", "password": "securepass123"})
    assert r.status_code == 200
    assert r.json()["user_id"] > 0
    r = client.post("/api/v1/auth/login", data={"username": "route_user", "password": "securepass123"})
    assert r.status_code == 200
    assert r.json()["token_type"] == "bearer"
    assert jwt.decode(r.json()["access_token"], options={"verify_signature": False})["sub"]


def test_register_rejects_a_taken_username(client, make_user):
    username, _ = make_user("taken")
    r = client.post("/api/v1/auth/register", json={"username": username, "password": "anotherpass"})
    assert r.status_code == 400


@pytest.mark.parametrize("username,password", [("nobody_here", "securepass123"), ("route_user2", "wrongpassword")])
def test_login_with_wrong_credentials_is_401(client, username, password):
    client.post("/api/v1/auth/register", json={"username": "route_user2", "password": "securepass123"})
    r = client.post("/api/v1/auth/login", data={"username": username, "password": password})
    assert r.status_code == 401
    assert r.json()["detail"] == "Incorrect username or password"


def test_upload_chat_stream_feedback_clear_list_delete(client, make_user):
    _, headers = make_user("routes")
    up = upload_text(client, headers)
    assert up.status_code == 200
    assert up.json() == {
        "filename": "zephyr_manual.txt", "pages": 1, "chunks": 1,
        "message": "Successfully ingested 'zephyr_manual.txt' (1 chunks from 1 page(s)).",
    }

    r = ask(client, headers, QUESTION)
    assert r.status_code == 200
    assert set(r.json()) == {"answer", "sources", "confidence", "session_id", "tool_used"}
    assert r.json()["session_id"] == "s1"

    status, events = ask_stream(client, headers, QUESTION)
    assert status == 200
    assert events[-1]["type"] == "done" and events[-1]["sources"]

    r = client.post("/api/v1/feedback", headers=headers, json={"session_id": "s1", "feedback": -1})
    assert r.json() == {"message": "Feedback recorded successfully."}

    r = client.post("/api/v1/session/clear", headers=headers, json={"question": "", "session_id": "s1"})
    assert r.json() == {"message": "Session cleared", "session_id": "s1"}

    assert client.get("/api/v1/documents", headers=headers).json() == {"documents": ["zephyr_manual.txt"], "count": 1}
    detailed = client.get("/api/v1/documents/detailed", headers=headers).json()
    assert detailed["count"] == 1
    assert set(detailed["documents"][0]) == {"id", "filename", "file_hash", "pages", "chunks", "size_bytes", "uploaded_at"}

    r = client.delete("/api/v1/documents", headers=headers)
    assert r.json() == {"message": "Cleared 1 chunks from the vector store.", "status": "cleared", "deleted": 1}


def test_stream_response_is_server_sent_events(client, make_user):
    _, headers = make_user("sse")
    r = client.post("/api/v1/chat/stream", headers=headers, json={"question": QUESTION})
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-cache"


# ── 401 ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("method,path", PROTECTED)
@pytest.mark.parametrize("token_kind", sorted(BAD_TOKENS))
def test_protected_routes_reject_a_bad_token(client, method, path, token_kind):
    r = getattr(client, method)(path, headers=_bearer(BAD_TOKENS[token_kind]))
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


def test_expired_token_says_so(client):
    r = client.get("/api/v1/documents", headers=_bearer(BAD_TOKENS["expired"]))
    assert r.json()["detail"] == "Token has expired. Please log in again."


# ── 422 on bad input ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("body", [
    {"password": "securepass123"},                      # no username
    {"username": "valid_name"},                         # no password
    {"username": "ab", "password": "securepass123"},    # too short
    {"username": "   ab   ", "password": "securepass123"},  # too short once trimmed
    {"username": "x" * 51, "password": "securepass123"},
    {"username": "bad name!", "password": "securepass123"},
    {"username": "valid_name", "password": "short"},
    {"username": "valid_name", "password": "p" * 129},
])
def test_register_rejects_bad_input(client, body):
    assert client.post("/api/v1/auth/register", json=body).status_code == 422


@pytest.mark.parametrize("form", [{}, {"username": "someone"}, {"password": "securepass123"}])
def test_login_rejects_missing_fields(client, form):
    assert client.post("/api/v1/auth/login", data=form).status_code == 422


def test_upload_without_a_file_is_422(client, make_user):
    _, headers = make_user("nofile")
    assert client.post("/api/v1/upload", headers=headers).status_code == 422


@pytest.mark.parametrize("path", ["/api/v1/chat", "/api/v1/chat/stream", "/api/v1/session/clear"])
@pytest.mark.parametrize("body", [
    {},                                                  # no question
    {"question": 42},                                    # not a string
    {"question": "hi", "use_agent": "sometimes"},        # not a boolean
    {"question": "hi", "session_id": "has space"},       # bad session id
])
def test_chat_routes_reject_bad_input(client, make_user, path, body):
    _, headers = make_user("bad")
    assert client.post(path, headers=headers, json=body).status_code == 422


@pytest.mark.parametrize("body", [{}, {"session_id": "s1"}, {"feedback": 1, "session_id": ""}, {"feedback": "up"}])
def test_feedback_rejects_bad_input(client, make_user, body):
    _, headers = make_user("badfb")
    assert client.post("/api/v1/feedback", headers=headers, json=body).status_code == 422


# ── Other rejections and server errors ────────────────────────────────────────

@pytest.mark.parametrize("filename,content,status", [
    ("notes.exe", b"MZ", 400),          # extension not allowed
    ("empty.txt", b"", 400),            # zero bytes
    ("blank.txt", b"   \n\t ", 422),    # nothing to extract
])
def test_upload_rejections(client, make_user, filename, content, status):
    _, headers = make_user("rej")
    r = client.post("/api/v1/upload", headers=headers, files={"file": (filename, content, "text/plain")})
    assert r.status_code == status, r.text
    assert client.get("/api/v1/documents", headers=headers).json()["count"] == 0


def test_upload_over_the_size_limit_is_rejected(client, make_user, monkeypatch):
    _, headers = make_user("big")
    monkeypatch.setattr(settings, "max_upload_bytes", 100)
    r = upload_text(client, headers, text="x" * 101)
    assert r.status_code == 400
    assert "too large" in r.json()["detail"]


def test_upload_ingestion_failure_is_500_and_records_nothing(client, make_user, monkeypatch):
    _, headers = make_user("ingfail")

    def broken(*args, **kwargs):
        raise RuntimeError("embedding service down")

    monkeypatch.setattr(routes_documents, "ingest_document", broken)
    assert upload_text(client, headers).status_code == 500
    assert client.get("/api/v1/documents", headers=headers).json()["count"] == 0


@pytest.mark.parametrize("path", ["/api/v1/chat", "/api/v1/chat/stream"])
def test_blank_question_is_400(client, make_user, path):
    _, headers = make_user("blank")
    assert client.post(path, headers=headers, json={"question": "   "}).status_code == 400


def test_chat_failure_is_500(client, make_user, fake_llm):
    _, headers = make_user("chatfail")
    upload_text(client, headers)
    fake_llm.fail_with = "model unavailable"
    r = ask(client, headers, QUESTION)
    assert r.status_code == 500
    assert r.json()["detail"].startswith("Query failed")


@pytest.mark.parametrize("method,path,module,target", [
    ("post", "/api/v1/feedback", routes_chat, "update_conversation_feedback"),
    ("get", "/api/v1/documents", routes_documents, "list_documents"),
    ("get", "/api/v1/documents/detailed", routes_documents, "get_all_documents_detailed"),
])
def test_storage_failure_is_500(client, make_user, monkeypatch, method, path, module, target):
    _, headers = make_user("dbfail")

    def broken(*args, **kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(module, target, broken)
    kwargs = {"json": {"session_id": "s1", "feedback": 1}} if method == "post" else {}
    assert getattr(client, method)(path, headers=headers, **kwargs).status_code == 500


# ── Rate limits (declared on register, login, upload, chat and chat/stream) ───

def _hit(client, route, headers):
    if route == "register":
        # A valid body: a request that fails validation never reaches the limiter
        return client.post("/api/v1/auth/register", json={"username": f"rl_{uuid.uuid4().hex[:8]}", "password": "securepass123"})
    if route == "login":
        return client.post("/api/v1/auth/login", data={"username": "nobody_at_all", "password": "wrongpass"})
    if route == "upload":
        return client.post("/api/v1/upload", headers=headers, files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    if route == "chat":
        return ask(client, headers, "anything")
    return client.post("/api/v1/chat/stream", headers=headers, json={"question": "anything"})


@pytest.mark.parametrize("route,limit", [
    ("register", 5), ("login", 10), ("upload", 10), ("chat", 30), ("chat_stream", 30),
])
def test_rate_limit(client, make_user, route, limit):
    _, headers = make_user("rl")
    # Each test starts with empty buckets, but make_user itself used one register and one login
    used = {"register": 1, "login": 1}.get(route, 0)
    for _ in range(limit - used):
        assert _hit(client, route, headers).status_code != 429
    r = _hit(client, route, headers)
    assert r.status_code == 429, (route, r.status_code)


def test_documents_list_has_no_rate_limit(client, make_user):
    _, headers = make_user("nolimit")
    for _ in range(40):
        assert client.get("/api/v1/documents", headers=headers).status_code == 200


def test_uploaded_bytes_are_recorded(client, make_user):
    _, headers = make_user("bytes")
    upload_text(client, headers)
    doc = client.get("/api/v1/documents/detailed", headers=headers).json()["documents"][0]
    assert doc["size_bytes"] == len(DOC_TEXT.encode())
    assert len(doc["file_hash"]) == 64
