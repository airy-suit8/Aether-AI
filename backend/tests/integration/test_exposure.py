"""
What the server shows the outside world (S10, Sprint 5 item 5): a request id on every response,
the security headers and a content security policy, server errors without their exception text,
and the API pages only in development.
"""

import pytest
from fastapi.testclient import TestClient

import main
from src.api import routes_chat
from src.api.middleware import CONTENT_SECURITY_POLICY, SECURITY_HEADERS
from src.core.config import settings


@pytest.mark.parametrize("path", ["/api/v1/health", "/api/v1/documents", "/api/v1/nowhere", "/"])
def test_every_response_carries_a_request_id_and_the_security_headers(client, path):
    r = client.get(path)
    assert len(r.headers["x-request-id"]) == 12
    for name, value in SECURITY_HEADERS.items():
        assert r.headers[name] == value
    assert r.headers["content-security-policy"] == CONTENT_SECURITY_POLICY


def test_each_request_gets_its_own_id(client):
    ids = {client.get("/api/v1/health").headers["x-request-id"] for _ in range(5)}
    assert len(ids) == 5


def test_the_policy_allows_no_remote_script_style_or_image():
    # S3: an image in a model's answer must not be fetched from another site
    rules = dict(rule.split(" ", 1) for rule in CONTENT_SECURITY_POLICY.split("; "))
    assert rules["default-src"] == "'self'" and rules["script-src"] == "'self'" and rules["style-src"] == "'self'"
    assert rules["img-src"] == "'self' data:" and rules["connect-src"] == "'self'"
    assert rules["frame-ancestors"] == "'none'" and rules["object-src"] == "'none'"


def test_an_error_no_route_catches_is_json_with_a_reference_and_no_detail(client, make_user, monkeypatch):
    _, headers = make_user("unhandled")

    def broken(*args, **kwargs):
        raise RuntimeError("secret detail /srv/aether/data")

    monkeypatch.setattr(routes_chat, "clear_session", broken)  # the session route catches nothing
    with TestClient(main.app, raise_server_exceptions=False) as quiet:
        r = quiet.post("/api/v1/session/clear", headers=headers, json={"question": "", "session_id": "s1"})
    assert r.status_code == 500
    rid = r.headers["x-request-id"]
    assert r.json() == {"detail": f"Something went wrong on the server. Please try again. Reference: {rid}"}
    assert "secret" not in r.text


@pytest.fixture
def app_in(monkeypatch):
    def build(environment):
        monkeypatch.setattr(settings, "environment", environment)
        return TestClient(main.create_app())
    return build


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_the_api_pages_are_off_in_production(app_in, path):
    assert app_in("production").get(path).status_code == 404
    assert app_in("development").get(path).status_code == 200


def test_the_api_pages_are_on_in_development_without_the_policy_that_would_block_them(app_in):
    r = app_in("development").get("/docs")
    assert "content-security-policy" not in r.headers  # they load their script from a CDN
    assert r.headers["x-content-type-options"] == "nosniff"
