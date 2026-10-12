"""Service -> database: each chat turn is saved once, with its real confidence and mode (R10)."""

import jwt
import pytest

from src.db import database
from helpers import upload_text, ask, ask_stream

QUESTION = "How often is the Zephyr turbine blade inspection?"


def _rows(headers, session_id):
    user_id = int(jwt.decode(headers["Authorization"].split()[1], options={"verify_signature": False})["sub"])
    conn = database._get_connection()
    rows = conn.execute(
        "SELECT question, confidence, mode FROM conversations WHERE user_id = ? AND session_id = ? ORDER BY id",
        (user_id, session_id),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


MODES = [
    ({}, "original"),
    ({"use_hybrid": True}, "hybrid"),
    ({"use_langchain": True}, "langchain"),
    ({"use_agent": True}, "agent"),
]


@pytest.mark.parametrize("modes,expected_mode", MODES)
@pytest.mark.parametrize("streaming", [False, True])
def test_turn_saved_once_with_confidence_and_mode(client, make_user, modes, expected_mode, streaming):
    _, headers = make_user("mem")
    upload_text(client, headers)
    if streaming:
        status, events = ask_stream(client, headers, QUESTION, session_id="m", **modes)
        assert events[-1]["type"] == "done"
    else:
        assert ask(client, headers, QUESTION, session_id="m", **modes).status_code == 200

    rows = _rows(headers, "m")
    assert len(rows) == 1, rows  # the agent's inner document search must not add its own row
    assert rows[0]["question"] == QUESTION
    assert rows[0]["mode"] == expected_mode
    assert rows[0]["confidence"] > 0
