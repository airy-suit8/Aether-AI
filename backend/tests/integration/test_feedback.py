"""
Feedback by turn (F10, Sprint 5 item 8): every saved answer comes with its turn_id, in the plain
reply and in the stream's done event, and POST /feedback rates exactly that turn. It used to rate
"the most recent message in the session", whichever that was by then.
"""

import pytest

from src.db import database
from helpers import ask, ask_stream, upload_text, user_id_of

QUESTION = "How often is the Zephyr turbine blade inspection?"
MODES = ["default", "hybrid", "langchain", "agent"]


def _feedback_of(turn_id):
    conn = database._get_connection()
    row = conn.execute("SELECT feedback FROM conversations WHERE id = ?", (turn_id,)).fetchone()
    conn.close()
    return row["feedback"]


@pytest.mark.parametrize("mode", MODES)
def test_every_saved_answer_names_its_turn(client, make_user, mode):
    _, headers = make_user("turnid")
    upload_text(client, headers)
    plain = ask(client, headers, QUESTION, session_id="t", mode=mode).json()["turn_id"]
    _, events = ask_stream(client, headers, QUESTION, session_id="t", mode=mode)
    streamed = events[-1]["turn_id"]
    turns = database.get_session_turns(user_id_of(headers), "t")
    assert [t["id"] for t in turns] == [plain, streamed]


def test_a_refusal_saves_no_turn_and_names_none(client, make_user):
    _, headers = make_user("noturn")
    r = ask(client, headers, "Anything at all?")  # no documents: refused
    assert r.json()["turn_id"] is None
    _, events = ask_stream(client, headers, "Anything at all?")
    assert events[-1]["turn_id"] is None


def test_feedback_rates_the_turn_named_not_the_latest_one(client, make_user):
    _, headers = make_user("rate")
    upload_text(client, headers)
    first = ask(client, headers, QUESTION, session_id="r").json()["turn_id"]
    second = ask(client, headers, "Who logs the Zephyr turbine blade inspection?", session_id="r").json()["turn_id"]

    assert client.post("/api/v1/feedback", headers=headers, json={"turn_id": first, "feedback": -1}).status_code == 200
    assert (_feedback_of(first), _feedback_of(second)) == (-1, 0)
    assert client.post("/api/v1/feedback", headers=headers, json={"turn_id": first, "feedback": 0}).status_code == 200
    assert _feedback_of(first) == 0  # 0 takes a rating back


def test_feedback_on_a_turn_that_does_not_exist_is_a_404(client, make_user):
    _, headers = make_user("rate404")
    r = client.post("/api/v1/feedback", headers=headers, json={"turn_id": 999999999, "feedback": 1})
    assert r.status_code == 404 and r.json()["detail"] == "No such answer."
