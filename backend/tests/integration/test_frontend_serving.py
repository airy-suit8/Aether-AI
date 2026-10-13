"""Backend -> UI: the built React app is served at /, after the API routes (B3)."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

import main


def _app_with_api_route():
    app = FastAPI()

    @app.get("/api/v1/ping")
    def ping():
        return {"pong": True}

    return app


def test_built_app_is_served_at_root_and_api_still_wins(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text('<!doctype html><div id="root"></div><script src="/assets/app.js"></script>')
    (tmp_path / "assets" / "app.js").write_text("console.log('app')")
    app = _app_with_api_route()
    main.mount_frontend(app, tmp_path)

    with TestClient(app) as c:
        root = c.get("/")
        assert root.status_code == 200
        assert '<div id="root">' in root.text
        assert c.get("/assets/app.js").text == "console.log('app')"
        assert c.get("/api/v1/ping").json() == {"pong": True}


def _built_app(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text('<!doctype html><div id="root"></div>')
    (tmp_path / "assets" / "app.js").write_text("console.log('app')")
    app = _app_with_api_route()
    main.mount_frontend(app, tmp_path)
    return app


def test_the_apps_own_paths_get_its_page(tmp_path):
    # Sprint 6, decision 7: the router's paths are real; a reload on any of them shows the app
    with TestClient(_built_app(tmp_path)) as c:
        for path in ("/login", "/chat", "/chat/session_1760000000000", "/settings", "/no/such/page"):
            page = c.get(path)
            assert page.status_code == 200, path
            assert page.headers["content-type"].startswith("text/html"), path
            assert '<div id="root">' in page.text, path
        # A file that exists is still served as itself
        assert c.get("/assets/app.js").text == "console.log('app')"


def test_an_unknown_api_path_stays_a_json_404(tmp_path):
    with TestClient(_built_app(tmp_path)) as c:
        for path in ("/api/v1/no-such-route", "/api/v2/chat", "/api/"):
            r = c.get(path)
            assert r.status_code == 404, path
            assert r.json() == {"detail": "Not Found"}, path
        assert c.get("/api/v1/ping").json() == {"pong": True}


def test_the_api_description_pages_are_not_pages_of_the_app(tmp_path):
    # Production turns /docs, /redoc and /openapi.json off; they must not become the app's page
    with TestClient(_built_app(tmp_path)) as c:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert c.get(path).status_code == 200  # FastAPI's own, in this development app
    production = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    main.mount_frontend(production, tmp_path)
    with TestClient(production) as c:
        for path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
            assert c.get(path).status_code == 404, path
        assert c.get("/chat").status_code == 200


def test_the_real_app_serves_its_pages_and_keeps_api_404s(client):
    # The suite's app serves frontend/dist when it has been built; without a build only / answers
    page = client.get("/chat/session_1")
    if main.FRONTEND_DIST.joinpath("index.html").is_file():
        assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    r = client.get("/api/v1/no-such-route")
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}


def test_without_a_build_root_explains_how_to_get_the_ui(tmp_path):
    app = _app_with_api_route()
    main.mount_frontend(app, tmp_path / "missing_dist")

    with TestClient(app) as c:
        root = c.get("/")
        assert root.status_code == 200
        assert "npm run build" in root.text and "npm run dev" in root.text
        assert c.get("/api/v1/ping").json() == {"pong": True}


def test_real_app_serves_root_and_api(client):
    assert client.get("/").status_code == 200
    assert client.get("/").headers["content-type"].startswith("text/html")
    assert client.get("/api/v1/health").json()["status"] == "ok"
