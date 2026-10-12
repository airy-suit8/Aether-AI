"""
Stop (Sprint 6, decision 11): closing the stream is the only signal the server gets, and a
stream closed before its answer is complete saves no turn, so a reload does not show an answer
the person stopped. There is no cancel route.

Two levels: the pipeline's event generator, closed after its first token, saves nothing in any
mode; and the app itself, driven over ASGI as uvicorn drives it, stops reading the answer when
the client disconnects, so the turn is never saved.
"""

import asyncio
import json
import time

import pytest

from helpers import ask_stream, upload_text, user_id_of
from src.db.database import get_session_turns
from src.pipeline import rag

import main

QUESTION = "How often is the Zephyr turbine blade inspection?"


@pytest.fixture
def reader(client, make_user):
    _, headers = make_user("stopper")
    upload_text(client, headers)
    return headers


@pytest.mark.parametrize("mode", ["default", "hybrid", "langchain", "agent"])
def test_events_closed_after_the_first_token_save_no_turn(reader, mode):
    user_id = user_id_of(reader)
    events = rag.events(user_id, QUESTION, session_id=f"closed-{mode}", mode=mode)
    assert next(events)["type"] == "token"
    events.close()  # what happens to the generator when the client goes away
    assert get_session_turns(user_id, f"closed-{mode}") == []

    # Read to the end, the same question saves its turn
    assert [e["type"] for e in rag.events(user_id, QUESTION, session_id=f"read-{mode}", mode=mode)][-1] == "done"
    assert len(get_session_turns(user_id, f"read-{mode}")) == 1


def _stream_request(headers, session_id):
    body = json.dumps({"question": QUESTION, "session_id": session_id}).encode()
    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1",
        "method": "POST", "scheme": "http", "path": "/api/v1/chat/stream", "raw_path": b"/api/v1/chat/stream",
        "query_string": b"", "root_path": "", "client": ("127.0.0.1", 50000), "server": ("testserver", 80),
        "headers": [
            (b"host", b"testserver"), (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"authorization", headers["Authorization"].encode()),
        ],
    }
    return scope, body


async def _ask_and_disconnect(headers, session_id):
    """Send a streamed question as uvicorn would, and disconnect once the first token arrives.
    Returns the body chunks received."""
    scope, body = _stream_request(headers, session_id)
    first_token = asyncio.Event()
    chunks = []
    requested = False

    async def receive():
        nonlocal requested
        if not requested:
            requested = True
            return {"type": "http.request", "body": body, "more_body": False}
        await first_token.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body" and message.get("body"):
            chunks.append(message["body"].decode())
            if '"type": "token"' in chunks[-1]:
                first_token.set()

    await asyncio.wait_for(main.app(scope, receive, send), timeout=30)
    return chunks


def test_a_stream_the_client_closes_saves_no_turn(client, reader, fake_llm):
    # The answer arrives word by word, a tenth of a second apart, as from a real model
    fake_llm.stream_delay = 0.1
    chunks = asyncio.run(_ask_and_disconnect(reader, "stopped"))
    assert any('"type": "token"' in c for c in chunks)
    assert not any('"type": "done"' in c for c in chunks)

    # Long enough for the rest of the answer, had the server gone on reading it
    words = len(rag.NOT_FOUND.split()) + 40
    time.sleep(min(words * fake_llm.stream_delay, 3.0))
    assert get_session_turns(user_id_of(reader), "stopped") == []

    # The same question, read to the end, is saved
    status, events = ask_stream(client, reader, QUESTION, session_id="finished")
    assert status == 200 and events[-1]["type"] == "done" and events[-1]["turn_id"]
    assert len(get_session_turns(user_id_of(reader), "finished")) == 1
