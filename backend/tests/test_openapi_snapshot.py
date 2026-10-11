"""
The API contract: the OpenAPI schema must match tests/openapi_snapshot.json.

A change to a route, a field or a model fails this test until the snapshot is refreshed and the
change is reviewed in the diff. Refresh it, from backend/, with:

    python -m pytest tests/test_openapi_snapshot.py --update-openapi-snapshot
"""

import json
from pathlib import Path

from main import app

SNAPSHOT = Path(__file__).parent / "openapi_snapshot.json"


def test_openapi_schema_matches_the_snapshot(request):
    current = app.openapi()
    if request.config.getoption("--update-openapi-snapshot"):
        with open(SNAPSHOT, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(current, indent=2, ensure_ascii=False) + "\n")
    saved = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert current == saved, (
        "The API schema changed. If the change is intended, refresh the snapshot with "
        "`python -m pytest tests/test_openapi_snapshot.py --update-openapi-snapshot` and review its diff."
    )


def test_snapshot_lists_every_api_route():
    saved = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    routes = {(path, method) for path, ops in saved["paths"].items() for method in ops}
    assert routes == {
        ("/api/v1/auth/register", "post"), ("/api/v1/auth/login", "post"), ("/api/v1/health", "get"),
        ("/api/v1/upload", "post"), ("/api/v1/chat", "post"), ("/api/v1/feedback", "post"),
        ("/api/v1/chat/stream", "post"), ("/api/v1/session/clear", "post"),
        ("/api/v1/documents", "get"), ("/api/v1/documents", "delete"), ("/api/v1/documents/detailed", "get"),
    }
