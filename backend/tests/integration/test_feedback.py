"""
Feedback by turn (F10, Sprint 5 item 8): every saved answer comes with its turn_id, in the plain
reply and in the stream's done event, and POST /feedback rates exactly that turn. It used to rate
"the most recent message in the session", whichever that was by then.
"""

import json
import uuid

import pytest

from src.core.config import BACKEND_DIR, DATA_DIR, settings
from src.db import database
from src.evaluation import export_feedback
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


# ── Thumbs-down answers as candidate dataset lines (Sprint 8, item 5) ────────

def _rate(client, headers, turn_id, value):
    assert client.post("/api/v1/feedback", headers=headers, json={"turn_id": turn_id, "feedback": value}).status_code == 200


def test_thumbs_down_answers_are_exported_as_lines_to_label(client, make_user, tmp_path, capsys):
    _, headers = make_user("export")
    upload_text(client, headers)
    probe = uuid.uuid4().hex
    down = ask(client, headers, f"{QUESTION} {probe} down", session_id="x").json()
    up = ask(client, headers, f"{QUESTION} {probe} up", session_id="x").json()
    back = ask(client, headers, f"{QUESTION} {probe} taken back", session_id="x").json()
    _rate(client, headers, down["turn_id"], -1)
    _rate(client, headers, up["turn_id"], 1)
    _rate(client, headers, back["turn_id"], -1)
    _rate(client, headers, back["turn_id"], 0)

    out = tmp_path / "candidates.jsonl"
    assert export_feedback.main(["--output", str(out)]) == 0
    mine = [line for line in map(json.loads, out.read_text(encoding="utf-8").splitlines()) if probe in line["question"]]
    assert len(mine) == 1
    line = mine[0]
    assert line["id"] == f"fb{down['turn_id']}" and line["question"] == f"{QUESTION} {probe} down"
    assert (line["expected_answer"], line["source"], line["page"]) == ("", "", None)  # for the owner to fill in
    assert line["answer_given"] == down["answer"] and line["mode"] == "original" and line["asked_at"]
    assert line["sources_given"] == [{k: s[k] for k in ("source", "page", "score")} for s in down["sources"]]

    # Only the count and the place are printed; the questions are in the file and nowhere else
    printed = capsys.readouterr()
    assert probe not in printed.out + printed.err
    assert f"to {out}." in printed.out
    for log in settings.log_dir.glob("*.log"):
        assert probe not in log.read_text(encoding="utf-8"), log.name


def test_the_export_is_written_under_the_data_folder_git_ignores_and_needs_a_database(tmp_path, monkeypatch, capsys):
    assert export_feedback.DEFAULT_OUTPUT.parent == DATA_DIR == BACKEND_DIR.parent / "data"
    assert "data/" in (BACKEND_DIR.parent / ".gitignore").read_text(encoding="utf-8").splitlines()
    monkeypatch.setattr(settings, "db_path", tmp_path / "missing.db")
    assert export_feedback.main(["--output", str(tmp_path / "out.jsonl")]) == 1
    assert "No database at" in capsys.readouterr().err and not (tmp_path / "out.jsonl").exists()
