"""
The line at which an answer reads as grounded (core/config.py, GROUNDED_LINES): measured for each
embedding model, since each spreads its similarities differently, and sent with every answer and
every conversation, so the page judges an answer by the line of the model that searched for it.
"""

from helpers import ask, ask_stream, upload_text
from src.core.config import GROUNDED_LINE_UNMEASURED, OLLAMA_EMBEDDING_MODEL, Settings, settings

QUESTION = "How often is the Zephyr turbine blade inspection?"


def test_each_embedding_model_has_its_own_line():
    assert Settings(_env_file=None, embedding_provider="gemini").grounded_line() == 0.6
    assert Settings(_env_file=None, embedding_provider="ollama").grounded_line() == 0.5
    assert Settings(_env_file=None, embedding_provider="ollama", embedding_model=OLLAMA_EMBEDDING_MODEL).grounded_line() == 0.5


def test_a_model_not_measured_gets_the_usual_line_and_a_set_line_wins():
    assert Settings(_env_file=None, embedding_provider="ollama", embedding_model="mxbai-embed-large").grounded_line() \
        == GROUNDED_LINE_UNMEASURED
    assert Settings(_env_file=None, embedding_provider="ollama", grounded_at=0.42).grounded_line() == 0.42


def test_every_answer_and_conversation_says_its_line(client, make_user, monkeypatch):
    monkeypatch.setattr(settings, "grounded_at", 0.42)
    _, headers = make_user("grounded")
    upload_text(client, headers)

    plain = ask(client, headers, QUESTION, session_id="talk")
    assert plain.status_code == 200 and plain.json()["grounded_at"] == 0.42
    status, events = ask_stream(client, headers, QUESTION, session_id="talk")
    assert status == 200 and events[-1]["type"] == "done" and events[-1]["grounded_at"] == 0.42
    refused = ask(client, headers, "Zephyr?", session_id="other")  # even a refusal says it
    assert refused.json()["grounded_at"] == 0.42

    history = client.get("/api/v1/sessions/talk/messages", headers=headers).json()
    assert history["grounded_at"] == 0.42 and len(history["turns"]) == 2
    token = client.post("/api/v1/sessions/talk/share", headers=headers).json()["token"]
    assert client.get(f"/api/v1/shared/{token}").json()["grounded_at"] == 0.42
