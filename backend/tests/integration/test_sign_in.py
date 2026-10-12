"""
Authentication (S7, Sprint 5 item 2): sign-up rules, an optional invite code, case-blind ASCII
usernames, a login that takes as long for an unknown name, 30-minute access tokens renewed
from an httpOnly refresh cookie, tokens refused once their user is gone, and an auth log.
"""

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

import main
from src.api import routes_auth
from src.core import security
from src.core.config import settings
from src.core.logging import auth_logger
from src.db import database
from helpers import user_id_of

PASSWORD = "securepass123"


@pytest.fixture
def fresh():
    """A client with its own cookie jar (the shared one holds whoever signed in last)."""
    with TestClient(main.app) as c:
        yield c


def _name(prefix="auth"):
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _register(client, username, password=PASSWORD, **extra):
    return client.post("/api/v1/auth/register", json={"username": username, "password": password, **extra})


def _login(client, username, password=PASSWORD):
    return client.post("/api/v1/auth/login", data={"username": username, "password": password})


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


# ── Sign-up rules ─────────────────────────────────────────────────────────────

def test_a_100_character_password_is_rejected_with_a_422(client):
    # Sprint 5 "done when"; with bcrypt 5 a 73- to 128-byte password used to give a 500
    r = _register(client, _name(), "p" * 100)
    assert r.status_code == 422
    assert "at most 72 bytes" in r.text


@pytest.mark.parametrize("password,status", [
    ("p" * 7, 422), ("p" * 8, 200),          # a longer minimum
    ("p" * 72, 200), ("p" * 73, 422),        # bcrypt's limit, in bytes
    ("é" * 36, 200), ("é" * 37, 422),        # 74 bytes in 37 characters
])
def test_password_length_is_8_characters_to_72_bytes(client, password, status):
    assert _register(client, _name(), password).status_code == status


def test_a_long_password_at_login_is_a_401_not_a_500(client):
    username = _name()
    _register(client, username)
    assert _login(client, username, "p" * 100).status_code == 401


@pytest.mark.parametrize("username", ["Zoë_smith", "ｆｕｌｌwidth", "bob​", "name with space"])
def test_usernames_are_ascii_only(client, username):
    assert _register(client, username).status_code == 422


def test_usernames_ignore_case_and_surrounding_spaces_at_register_and_login_alike(client):
    username = _name("Case")
    assert _register(client, f"  {username}  ").status_code == 200
    assert _register(client, username.upper()).status_code == 400  # the same name in other letters
    for typed in (username, username.lower(), username.upper(), f"  {username}  "):
        assert _login(client, typed).status_code == 200, typed


def test_two_registrations_racing_for_one_name_give_a_400_not_a_500(client, monkeypatch):
    username = _name()
    _register(client, username)
    monkeypatch.setattr(routes_auth, "get_user_by_username", lambda name: None)  # both passed the check
    r = _register(client, username.upper())
    assert r.status_code == 400 and r.json()["detail"] == "Username already registered"


def test_the_database_refuses_a_name_that_differs_only_in_case():
    username = _name()
    database.create_user(username, "hash")
    with pytest.raises(sqlite3.IntegrityError):
        database.create_user(username.upper(), "hash")


# ── Invite code ───────────────────────────────────────────────────────────────

def test_registration_is_open_when_no_invite_code_is_set(client):
    assert settings.invite_code == ""
    assert _register(client, _name()).status_code == 200
    assert _register(client, _name(), invite_code="anything").status_code == 200


@pytest.mark.parametrize("given,status", [(None, 403), ("", 403), ("wrong", 403), ("letmein-2026", 200)])
def test_registration_needs_the_invite_code_once_one_is_set(client, monkeypatch, given, status):
    monkeypatch.setattr(settings, "invite_code", "letmein-2026")
    extra = {} if given is None else {"invite_code": given}
    username = _name()
    r = _register(client, username, **extra)
    assert r.status_code == status
    if status == 403:
        assert r.json()["detail"] == "Registration needs a valid invite code."
        assert _login(client, username).status_code == 401  # and no account was made


# ── Login timing ──────────────────────────────────────────────────────────────

def test_a_login_for_an_unknown_name_still_checks_a_password(client, monkeypatch):
    # S7: an unknown name used to skip bcrypt, so it answered measurably faster
    checked = []
    real = security.verify_password
    monkeypatch.setattr(routes_auth, "verify_password", lambda p, h: checked.append(h) or real(p, h))
    assert _login(client, _name("nobody")).status_code == 401
    assert checked == [security.unknown_user_hash()] and checked[0].startswith("$2b$")


# ── Tokens ────────────────────────────────────────────────────────────────────

def test_access_tokens_last_30_minutes(fresh):
    username = _name()
    _register(fresh, username)
    token = _login(fresh, username).json()["access_token"]
    claims = jwt.decode(token, options={"verify_signature": False})
    lifetime = datetime.fromtimestamp(claims["exp"], timezone.utc) - datetime.now(timezone.utc)
    assert timedelta(minutes=29) < lifetime <= timedelta(minutes=30)
    assert claims["type"] == "access" and claims["tid"] == database.get_tenant_id(int(claims["sub"]))
    assert 30 <= settings.access_token_minutes <= 60


def test_login_sets_an_http_only_refresh_cookie_for_the_auth_routes_only(fresh):
    username = _name()
    _register(fresh, username)
    cookie = _login(fresh, username).headers["set-cookie"]
    assert cookie.startswith("aether_refresh=")
    attributes = {part.strip().split("=")[0].lower() for part in cookie.split(";")}
    assert {"httponly", "path", "samesite", "max-age"} <= attributes
    assert "Path=/api/v1/auth" in cookie and "SameSite=strict" in cookie
    assert f"Max-Age={7 * 24 * 3600}" in cookie


def test_the_refresh_cookie_gives_a_new_access_token_that_works(fresh):
    username = _name()
    _register(fresh, username)
    first = _login(fresh, username).json()["access_token"]
    r = fresh.post("/api/v1/auth/refresh")
    assert r.status_code == 200
    renewed = r.json()["access_token"]
    assert renewed != first and r.json()["expires_in"] == 30 * 60
    assert fresh.get("/api/v1/documents", headers=_bearer(renewed)).status_code == 200
    assert "aether_refresh=" in r.headers["set-cookie"]  # and the cookie is renewed with it


def test_refresh_without_a_cookie_is_a_401(fresh):
    fresh.cookies.clear()
    assert fresh.post("/api/v1/auth/refresh").status_code == 401


def test_logout_removes_the_cookie_so_refresh_fails(fresh):
    username = _name()
    _register(fresh, username)
    _login(fresh, username)
    r = fresh.post("/api/v1/auth/logout")
    assert r.status_code == 200 and r.json() == {"message": "Signed out"}
    assert fresh.post("/api/v1/auth/refresh").status_code == 401


def test_a_refresh_token_is_not_an_access_token_and_the_reverse(fresh):
    username = _name()
    _register(fresh, username)
    access = _login(fresh, username).json()["access_token"]
    refresh = fresh.cookies.get("aether_refresh")
    assert fresh.get("/api/v1/documents", headers=_bearer(refresh)).status_code == 401
    fresh.cookies.clear()
    fresh.cookies.set("aether_refresh", access, path="/api/v1/auth")
    assert fresh.post("/api/v1/auth/refresh").status_code == 401


def test_a_token_for_a_user_who_is_gone_is_refused(fresh):
    # S7: a token for a user id that does not exist used to be accepted
    username = _name()
    _register(fresh, username)
    headers = _bearer(_login(fresh, username).json()["access_token"])
    assert fresh.get("/api/v1/documents", headers=headers).status_code == 200

    conn = database._get_connection()
    conn.execute("DELETE FROM users WHERE id = ?", (user_id_of(headers),))
    conn.commit()
    conn.close()
    assert fresh.get("/api/v1/documents", headers=headers).status_code == 401
    assert fresh.post("/api/v1/auth/refresh").status_code == 401


def test_a_token_from_before_a_database_reset_does_not_sign_in_the_new_owner_of_its_id(fresh, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "db_path", tmp_path / "first.db")
    database.init_db()
    _register(fresh, "first_owner")
    old = _bearer(_login(fresh, "first_owner").json()["access_token"])

    monkeypatch.setattr(settings, "db_path", tmp_path / "second.db")
    database.init_db()
    _register(fresh, "second_owner")
    new = _bearer(_login(fresh, "second_owner").json()["access_token"])
    assert user_id_of(old) == user_id_of(new)  # the same number, another person
    assert fresh.get("/api/v1/documents", headers=new).status_code == 200
    assert fresh.get("/api/v1/documents", headers=old).status_code == 401


# ── The auth log ──────────────────────────────────────────────────────────────

def test_sign_ups_sign_ins_and_failures_are_logged_without_passwords(fresh):
    username = _name("logged")
    secret = f"pw-{uuid.uuid4().hex}"
    _register(fresh, username, secret)
    _login(fresh, username, "wrong-password-1")
    headers = _bearer(_login(fresh, username, secret).json()["access_token"])
    for handler in auth_logger.handlers:
        handler.flush()
    text = (settings.log_dir / "auth.log").read_text(encoding="utf-8")
    assert secret not in text and "wrong-password-1" not in text
    lines = [json.loads(line) for line in text.splitlines()]
    user_id = user_id_of(headers)
    assert any(e["event"] == "register_ok" and e["user_id"] == user_id for e in lines)
    assert any(e["event"] == "login_failed" and e["username"] == username and e["known_user"] for e in lines)
    assert any(e["event"] == "login_ok" and e["user_id"] == user_id for e in lines)
