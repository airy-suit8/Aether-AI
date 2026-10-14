"""
Every reply has a model in the schema (Sprint 6, decision 5), and the models describe what is
sent: the streamed events validate against theirs, and a reply read through its model keeps
the same fields and values as before (a source without a number has no "number" key, and the
detailed document list still carries file_hash).
"""

import pytest
from pydantic import TypeAdapter

from helpers import DOC_TEXT, ask, ask_stream, upload_text
from src.api.schemas import StreamEvent
from src.core.config import settings

EVENTS = TypeAdapter(StreamEvent)
# A passage the app stored also says which document it is, of what kind, and where it sits
SOURCE_KEYS = {"source", "page", "snippet", "score", "document_id", "kind", "passage", "passages"}
QUESTION = "How often is the Zephyr turbine blade inspection?"


@pytest.fixture
def reader(client, make_user):
    _, headers = make_user("models")
    upload_text(client, headers, text=DOC_TEXT)
    return headers


@pytest.mark.parametrize("mode", ["default", "hybrid", "langchain", "agent"])
def test_every_streamed_event_matches_its_model(client, reader, mode):
    status, events = ask_stream(client, reader, QUESTION, session_id=f"models-{mode}", mode=mode)
    assert status == 200
    assert [e["type"] for e in events][-1] == "done"
    for event in events:
        EVENTS.validate_python(event)
    done = events[-1]
    assert done["sources"] and all(set(s) - {"number"} == SOURCE_KEYS for s in done["sources"])
    assert ("tool_used" in done) == (mode == "agent")


def test_an_error_event_matches_its_model(client, reader, fake_llm):
    fake_llm.fail_with = "boom"
    _, events = ask_stream(client, reader, QUESTION, session_id="models-error")
    assert events[-1]["type"] == "error"
    EVENTS.validate_python(events[-1])


def test_cited_sources_keep_their_number_and_others_have_none(client, reader, monkeypatch):
    monkeypatch.setattr(settings, "answer_from", "summary")  # an answer from a summary cites nothing
    plain = ask(client, reader, QUESTION, session_id="models-plain").json()
    assert all(set(s) == SOURCE_KEYS for s in plain["sources"])

    monkeypatch.setattr(settings, "answer_from", "chunks")
    cited = ask(client, reader, QUESTION, session_id="models-cited").json()
    assert [s["number"] for s in cited["sources"]] == [1]
    _, events = ask_stream(client, reader, QUESTION, session_id="models-cited-stream")
    EVENTS.validate_python(events[-1])
    assert events[-1]["sources"][0]["number"] == 1

    # Read back for a reload, each source is as it was sent
    turns = client.get("/api/v1/sessions/models-plain/messages", headers=reader).json()["turns"]
    assert turns[0]["sources"] == plain["sources"]
    turns = client.get("/api/v1/sessions/models-cited/messages", headers=reader).json()["turns"]
    assert turns[0]["sources"] == cited["sources"]


def test_document_replies_keep_their_fields(client, reader):
    detailed = client.get("/api/v1/documents/detailed", headers=reader).json()
    assert detailed["count"] == 1
    assert set(detailed["documents"][0]) == {
        "id", "filename", "file_hash", "pages", "chunks", "size_bytes", "uploaded_at", "status", "error", "title", "kind"}
    assert len(detailed["documents"][0]["file_hash"]) == 64

    assert client.get("/api/v1/documents", headers=reader).json() == {"documents": ["zephyr_manual.txt"], "count": 1}
    deleted = client.delete(f"/api/v1/documents/{detailed['documents'][0]['id']}", headers=reader).json()
    assert set(deleted) == {"message", "filename", "deleted"}
    assert client.delete("/api/v1/documents", headers=reader).json() == {
        "message": "Cleared 0 chunks from the vector store.", "status": "cleared", "deleted": 0}


def test_small_replies_keep_their_fields(client, reader):
    assert client.get("/api/v1/health").json() == {"status": "ok"}
    assert client.post("/api/v1/session/clear", headers=reader, json={"question": "", "session_id": "x"}).json() == {
        "message": "Session cleared", "session_id": "x"}
    assert client.post("/api/v1/auth/logout").json() == {"message": "Signed out"}
