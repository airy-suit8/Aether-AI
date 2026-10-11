"""Small HTTP helpers shared by the integration tests."""

import json

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
