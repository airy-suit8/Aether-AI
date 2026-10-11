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
