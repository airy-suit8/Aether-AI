"""Request limits: question length on both chat routes, session_id and feedback ranges (S9)."""

import pytest

from helpers import upload_text, ask, ask_stream


def test_stream_rejects_question_over_5000_chars(client, make_user, fake_llm):
    _, headers = make_user("long")
    status, _ = ask_stream(client, headers, "a" * 5001)
    assert status == 400
    assert fake_llm.prompts == []  # nothing reached the model


def test_chat_rejects_question_over_5000_chars(client, make_user):
    _, headers = make_user("longc")
    assert ask(client, headers, "a" * 5001).status_code == 400


def test_question_of_exactly_5000_chars_is_accepted(client, make_user):
    _, headers = make_user("edge")
    upload_text(client, headers)
    status, events = ask_stream(client, headers, "Zephyr turbine " + "a" * (5000 - 15))
    assert status == 200
    assert events[-1]["type"] == "done"


@pytest.mark.parametrize("session_id", ["", "x" * 101, "has space", "semi;colon", "new\nline"])
def test_bad_session_ids_are_rejected(client, make_user, session_id):
    _, headers = make_user("sid")
    assert ask(client, headers, "hello", session_id=session_id).status_code == 422
    status, _ = ask_stream(client, headers, "hello", session_id=session_id)
    assert status == 422


def test_frontend_style_session_id_is_accepted(client, make_user):
    _, headers = make_user("sidok")
    r = client.post("/api/v1/session/clear", headers=headers, json={"question": "", "session_id": "session_1760180000000"})
    assert r.status_code == 200


@pytest.mark.parametrize("value", [-2, 2, 5, 100])
def test_feedback_outside_minus_one_to_one_is_rejected(client, make_user, value):
    _, headers = make_user("fb")
    r = client.post("/api/v1/feedback", headers=headers, json={"turn_id": 1, "feedback": value})
    assert r.status_code == 422


@pytest.mark.parametrize("value", [-1, 0, 1])
def test_feedback_values_accepted(client, make_user, value):
    _, headers = make_user("fbok")
    upload_text(client, headers)
    turn_id = ask(client, headers, "How often is the Zephyr turbine blade inspection?").json()["turn_id"]
    r = client.post("/api/v1/feedback", headers=headers, json={"turn_id": turn_id, "feedback": value})
    assert r.status_code == 200
