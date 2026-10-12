"""One version number (Sprint 7, decision 9): the API's (in its schema), and the web app's
package.json, which the interface shows under Settings, System."""

import json
from pathlib import Path

from main import app
from src.core.config import APP_VERSION

PACKAGE_JSON = Path(__file__).resolve().parents[2] / "frontend" / "package.json"


def test_the_api_and_the_web_app_have_one_version():
    assert app.version == APP_VERSION
    assert json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))["version"] == APP_VERSION
