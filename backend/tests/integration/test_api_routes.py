"""
Every API route: success, 401 without a valid token, 422 on bad input, and the declared rate limit.

The end-to-end test already walks the happy path; this file fills in the rest route by route.
Routes with no request body or parameters (health, document list, detailed list, delete) have
no input that could be rejected with a 422.
"""

import json
import uuid
from datetime import timedelta

import jwt
import pytest

from src.api import routes_chat, routes_documents
from src.core import security
from src.pipeline import documents
from src.core.config import settings
from src.core.logging import error_logger, request_logger
from helpers import DOC_TEXT, upload_text, ask, ask_stream, status_of, user_id_of

QUESTION = "How often is the Zephyr turbine blade inspection?"

PROTECTED = [
    ("post", "/api/v1/upload"), ("post", "/api/v1/chat"), ("post", "/api/v1/chat/stream"),
    ("post", "/api/v1/feedback"), ("post", "/api/v1/session/clear"),
    ("get", "/api/v1/documents"), ("get", "/api/v1/documents/detailed"), ("delete", "/api/v1/documents"),
    ("delete", "/api/v1/documents/1"), ("get", "/api/v1/documents/1"),
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

def test_health_is_public_and_reports_only_the_status(client):
    # S10: it used to return the version, the uptime and counts across every user
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_register_then_login(client):
    r = client.post("/api/v1/auth/register", json={"username": "route_user", "password": "securepass123"})
    assert r.status_code == 200
    assert r.json() == {"message": "User registered successfully"}  # no sequential id (S7)
    r = client.post("/api/v1/auth/login", data={"username": "route_user", "password": "securepass123"})
    assert r.status_code == 200
    assert r.json()["token_type"] == "bearer" and r.json()["expires_in"] == 30 * 60
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
    assert up.status_code == 202  # accepted; read in the background (R12)
    body = up.json()
    document_id = body.pop("document_id")
    assert isinstance(document_id, int)
    assert body == {"filename": "zephyr_manual.txt", "status": "processing", "replaces": False,
                    "message": "Reading 'zephyr_manual.txt'."}
    document = client.get(f"/api/v1/documents/{document_id}", headers=headers).json()
    assert {k: document[k] for k in ("id", "filename", "status", "error", "pages", "chunks")} == {
        "id": document_id, "filename": "zephyr_manual.txt", "status": "ready", "error": None, "pages": 1, "chunks": 1}

    r = ask(client, headers, QUESTION)
    assert r.status_code == 200
    assert set(r.json()) == {"answer", "sources", "confidence", "session_id", "tool_used", "steps", "turn_id", "usage"}
    assert r.json()["session_id"] == "s1"
    turn_id = r.json()["turn_id"]

    status, events = ask_stream(client, headers, QUESTION)
    assert status == 200
    assert events[-1]["type"] == "done" and events[-1]["sources"]

    r = client.post("/api/v1/feedback", headers=headers, json={"turn_id": turn_id, "feedback": -1})
    assert r.json() == {"message": "Feedback recorded successfully."}

    r = client.post("/api/v1/session/clear", headers=headers, json={"question": "", "session_id": "s1"})
    assert r.json() == {"message": "Session cleared", "session_id": "s1"}

    assert client.get("/api/v1/documents", headers=headers).json() == {"documents": ["zephyr_manual.txt"], "count": 1}
    detailed = client.get("/api/v1/documents/detailed", headers=headers).json()
    assert detailed["count"] == 1
    assert set(detailed["documents"][0]) == {"id", "filename", "file_hash", "pages", "chunks", "size_bytes", "uploaded_at",
                                             "status", "error"}

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
    {"username": "valid_name", "password": "seven77"},     # under 8 (S7)
    {"username": "valid_name", "password": "p" * 129},
    {"username": "valid_name", "password": "p" * 73},       # over bcrypt's 72 bytes (S7)
    {"username": "Ünïcode", "password": "securepass123"},   # not ASCII: look-alike names (S7)
])
def test_register_rejects_bad_input(client, body):
    assert client.post("/api/v1/auth/register", json=body).status_code == 422


@pytest.mark.parametrize("form", [{}, {"username": "someone"}, {"password": "securepass123"}])
def test_login_rejects_missing_fields(client, form):
    assert client.post("/api/v1/auth/login", data=form).status_code == 422


def test_upload_without_a_file_is_422(client, make_user):
    _, headers = make_user("nofile")
    assert client.post("/api/v1/upload", headers=headers).status_code == 422
    assert client.post("/api/v1/upload", headers=headers, files={"other": ("a.txt", b"hi")}).status_code == 422
    assert client.post("/api/v1/upload", headers=headers, data={"file": "just text"}).status_code == 422


@pytest.mark.parametrize("path", ["/api/v1/chat", "/api/v1/chat/stream", "/api/v1/session/clear"])
@pytest.mark.parametrize("body", [
    {},                                                  # no question
    {"question": 42},                                    # not a string
    {"question": "hi", "mode": "sometimes"},             # not a mode
    {"question": "hi", "use_agent": True},               # the old flags are gone
    {"question": "hi", "session_id": "has space"},       # bad session id
])
def test_chat_routes_reject_bad_input(client, make_user, path, body):
    _, headers = make_user("bad")
    assert client.post(path, headers=headers, json=body).status_code == 422


@pytest.mark.parametrize("body", [
    {}, {"turn_id": 1}, {"feedback": 1}, {"turn_id": 1, "feedback": "up"}, {"turn_id": "one", "feedback": 1},
    {"session_id": "s1", "feedback": 1},              # the old shape: rated "the latest turn of the session" (F10)
    {"turn_id": 1, "feedback": 1, "session_id": "s1"},
])
def test_feedback_rejects_bad_input(client, make_user, body):
    _, headers = make_user("badfb")
    assert client.post("/api/v1/feedback", headers=headers, json=body).status_code == 422


# ── Other rejections and server errors ────────────────────────────────────────

@pytest.mark.parametrize("filename,content,status", [
    ("notes.exe", b"MZ", 400),          # extension not allowed
    ("empty.txt", b"", 400),            # zero bytes
])
def test_upload_rejections(client, make_user, filename, content, status):
    _, headers = make_user("rej")
    r = client.post("/api/v1/upload", headers=headers, files={"file": (filename, content, "text/plain")})
    assert r.status_code == status, r.text
    assert client.get("/api/v1/documents/detailed", headers=headers).json()["count"] == 0


def test_a_file_with_nothing_to_read_is_accepted_then_fails_with_a_reason(client, make_user):
    # It is read in the background (R12), so the reason is in its status rather than the reply
    _, headers = make_user("blank")
    r = client.post("/api/v1/upload", headers=headers, files={"file": ("blank.txt", b"   \n\t ", "text/plain")})
    document = status_of(client, headers, r)
    assert document["status"] == "failed" and document["error"] == "No text could be extracted from the document."
    assert client.get("/api/v1/documents", headers=headers).json()["count"] == 0  # not searchable


def test_upload_over_the_size_limit_is_rejected(client, make_user, monkeypatch):
    _, headers = make_user("big")
    monkeypatch.setattr(settings, "max_upload_bytes", 100)
    r = upload_text(client, headers, text="x" * 101)
    assert r.status_code == 413  # was a 400, after the whole file had been read into memory (S4)
    assert "too large" in r.json()["detail"]


def test_an_ingestion_failure_is_reported_in_the_status_with_a_reference_only(client, make_user, monkeypatch):
    _, headers = make_user("ingfail")

    def broken(*args, **kwargs):
        raise RuntimeError("embedding service down")

    working = documents.ingest_document
    monkeypatch.setattr(documents, "ingest_document", broken)
    r = upload_text(client, headers)
    document = status_of(client, headers, r)
    assert document["status"] == "failed"
    assert document["error"] == ("Something went wrong on the server while reading this file. Please try again. "
                                 f"Reference: {r.headers['x-request-id']}")
    assert client.get("/api/v1/documents", headers=headers).json()["count"] == 0
    monkeypatch.setattr(documents, "ingest_document", working)
    # A failed upload does not block the same file: it can be uploaded again
    assert status_of(client, headers, upload_text(client, headers))["status"] == "ready"


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
    # S10: a general message and the request's reference, never the exception's text
    assert r.json()["detail"] == f"Something went wrong on the server. Please try again. Reference: {r.headers['x-request-id']}"


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
    kwargs = {"json": {"turn_id": 1, "feedback": 1}} if method == "post" else {}
    r = getattr(client, method)(path, headers=headers, **kwargs)
    assert r.status_code == 500
    assert "database is locked" not in r.text and r.headers["x-request-id"] in r.json()["detail"]


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


def _assert_rate_limited(r):
    """A 429 in the shape of every other error, with how long to wait (N1, second audit)."""
    assert r.status_code == 429, r.status_code
    wait = int(r.headers["retry-after"])
    assert 1 <= wait <= 60  # every limit here is per minute
    assert r.json() == {"detail": f"Too many requests. Please wait {wait} second{'s' if wait != 1 else ''} and try again."}


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
    _assert_rate_limited(r)


@pytest.mark.parametrize("path", ["/api/v1/documents", "/api/v1/health"])
def test_a_route_without_a_limit_of_its_own_gets_the_default(client, make_user, path):
    # S8: only five routes had a limit; now every route has one
    assert settings.rate_limit_default == "120/minute"
    _, headers = make_user("default")
    for _ in range(120):
        assert client.get(path, headers=headers).status_code == 200
    _assert_rate_limited(client.get(path, headers=headers))


def test_every_api_route_has_a_limit():
    from src.api.deps import limiter
    assert limiter._default_limits  # applied by the middleware to every route without a decorator
    own = {name.rsplit(".", 1)[1] for name in limiter._route_limits}
    assert own == {"register", "login", "upload_document", "chat", "chat_stream"}
    assert not limiter._exempt_routes


def test_signed_in_users_have_their_own_allowance_even_from_one_address(client, make_user):
    # S8: limits were keyed by socket address, so behind a proxy everyone shared one bucket
    _, alice = make_user("alice_rl")
    _, bob = make_user("bob_rl")
    for _ in range(30):
        assert ask(client, alice, "anything").status_code != 429
    assert ask(client, alice, "anything").status_code == 429
    assert ask(client, bob, "anything").status_code == 200  # same address, another user


def test_requests_without_a_valid_token_share_their_address_s_allowance(client):
    from starlette.requests import Request
    from src.api.deps import rate_limit_key

    def key(authorization=None):
        headers = [(b"authorization", authorization.encode())] if authorization else []
        return rate_limit_key(Request({"type": "http", "headers": headers, "client": ("10.0.0.7", 1234)}))

    good = security.create_access_token({"sub": "42"})
    assert key(f"Bearer {good}") == "user:42"
    for bad in (None, "Bearer not-a-jwt", *(f"Bearer {token}" for token in BAD_TOKENS.values())):
        assert key(bad) == "address:10.0.0.7"


def test_uploaded_bytes_are_recorded(client, make_user):
    _, headers = make_user("bytes")
    upload_text(client, headers)
    doc = client.get("/api/v1/documents/detailed", headers=headers).json()["documents"][0]
    assert doc["size_bytes"] == len(DOC_TEXT.encode())
    assert len(doc["file_hash"]) == 64


# ── Log files ─────────────────────────────────────────────────────────────────

def _log_lines(name):
    for logger in (request_logger, error_logger):
        for handler in logger.handlers:
            handler.flush()
    path = settings.log_dir / name
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_chat_requests_are_logged_as_json_with_the_user_and_request_but_not_the_question(client, make_user):
    # AUDIT_REPORT wiring map, "Logger ↔ routes": requests.log was absent on disk (its logger was
    # named "requests", the HTTP library's). S10: the lines are structured, carry the user and the
    # request id, and never the question.
    _, headers = make_user("logline")
    user_id = user_id_of(headers)
    question = f"log probe {uuid.uuid4().hex}"
    r = ask(client, headers, question)
    assert r.status_code == 200
    status, _ = ask_stream(client, headers, question)
    assert status == 200

    mine = [line for line in _log_lines("requests.log") if line.get("user_id") == user_id]
    chat = [line for line in mine if line["event"] == "chat_ok"]
    assert len(chat) == 1 and chat[0]["request_id"] == r.headers["x-request-id"]
    assert chat[0]["question_chars"] == len(question) and chat[0]["mode"] == "default"
    assert [line["event"] for line in mine if line["event"] == "stream_request"] == ["stream_request"]
    for name in ("requests.log", "uploads.log", "errors.log"):
        path = settings.log_dir / name
        assert not path.exists() or question not in path.read_text(encoding="utf-8"), name


def test_a_failed_request_is_logged_with_its_traceback_under_the_reference_given(client, make_user, fake_llm):
    _, headers = make_user("logerr")
    upload_text(client, headers)
    fake_llm.fail_with = f"model unavailable {uuid.uuid4().hex}"
    r = ask(client, headers, QUESTION)
    assert r.status_code == 500 and fake_llm.fail_with not in r.text
    line = [line for line in _log_lines("errors.log") if line.get("request_id") == r.headers["x-request-id"]]
    assert len(line) == 1 and line[0]["event"] == "chat_failed" and line[0]["user_id"] == user_id_of(headers)
    assert fake_llm.fail_with in line[0]["exception"] and "Traceback" in line[0]["exception"]
