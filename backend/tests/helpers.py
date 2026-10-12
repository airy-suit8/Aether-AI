"""Small HTTP helpers shared by the integration tests."""

import json

import jwt

from src.db.database import get_tenant_id

DOC_TEXT = (
    "The Zephyr turbine maintenance schedule requires a blade inspection every 90 days. "
    "The inspection is carried out by the Orion field team and logged in the Halcyon register."
)


def upload_text(client, headers, filename="zephyr_manual.txt", text=DOC_TEXT):
    return client.post(
        "/api/v1/upload",
        headers=headers,
        files={"file": (filename, text.encode("utf-8"), "text/plain")},
    )


def ask(client, headers, question, session_id="s1", **modes):
    return client.post(
        "/api/v1/chat",
        headers=headers,
        json={"question": question, "session_id": session_id, **modes},
    )


def ask_stream(client, headers, question, session_id="s1", **modes):
    """POST /chat/stream and return (status_code, list of parsed SSE events)."""
    r = client.post(
        "/api/v1/chat/stream",
        headers=headers,
        json={"question": question, "session_id": session_id, **modes},
    )
    events = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
    return r.status_code, events


def user_id_of(headers):
    """The user id in a test user's token."""
    return int(jwt.decode(headers["Authorization"].split()[1], options={"verify_signature": False})["sub"])


def tenant_of(headers):
    """The tenant id that keys a test user's chunks in the vector store."""
    return get_tenant_id(user_id_of(headers))
