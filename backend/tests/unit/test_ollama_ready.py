"""
start.bat asks src/ollama_ready.py whether Ollama must be started: only when the settings use it,
on this computer, and it does not answer. A small HTTP server on this computer stands in for
Ollama; nothing else is reached.
"""

import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from src import ollama_ready
from src.core.config import settings


class _Version(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/api/version" else 404)
        self.end_headers()
        self.wfile.write(b'{"version":"0.40.4"}')

    def log_message(self, *args):
        pass


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve(port: int) -> HTTPServer:
    server = HTTPServer(("127.0.0.1", port), _Version)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def uses_ollama(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "ollama")


def test_a_setup_without_ollama_asks_nothing(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "embedding_provider", "gemini")
    monkeypatch.setattr(ollama_ready, "answering", lambda url, timeout=2.0: pytest.fail("not needed"))
    assert ollama_ready.check() == 0


def test_ollama_for_the_embeddings_alone_is_needed_too(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "embedding_provider", "ollama")
    assert ollama_ready.needed()


def test_an_ollama_that_answers_needs_nothing(uses_ollama, monkeypatch, capsys):
    port = _free_port()
    server = _serve(port)
    try:
        monkeypatch.setattr(settings, "ollama_url", f"http://127.0.0.1:{port}")
        assert ollama_ready.check() == 0
    finally:
        server.shutdown()
    assert "answering" in capsys.readouterr().out


def test_an_ollama_on_this_computer_that_does_not_answer_is_to_be_started(uses_ollama, monkeypatch, capsys):
    monkeypatch.setattr(settings, "ollama_url", f"http://127.0.0.1:{_free_port()}")
    assert ollama_ready.check() == ollama_ready.NOT_ANSWERING == 3
    assert "does not answer" in capsys.readouterr().out


def test_waiting_finds_an_ollama_that_starts_late(uses_ollama, monkeypatch):
    port = _free_port()
    monkeypatch.setattr(settings, "ollama_url", f"http://localhost:{port}")
    servers = []
    threading.Timer(0.5, lambda: servers.append(_serve(port))).start()
    started = time.monotonic()
    try:
        assert ollama_ready.check(wait=10, poll=0.1) == 0
    finally:
        for server in servers:
            server.shutdown()
    assert time.monotonic() - started < 5


def test_one_on_another_computer_is_reported_not_started(uses_ollama, monkeypatch, capsys):
    monkeypatch.setattr(settings, "ollama_url", "http://192.0.2.10:11434")
    monkeypatch.setattr(ollama_ready, "answering", lambda url, timeout=2.0: False)
    assert ollama_ready.check() == 0
    assert "on another computer" in capsys.readouterr().out


def test_the_command_line_takes_the_wait(uses_ollama, monkeypatch):
    seen = []
    monkeypatch.setattr(ollama_ready, "check", lambda wait=0.0: seen.append(wait) or 0)
    assert ollama_ready.main(["--wait", "30"]) == 0
    assert seen == [30.0]
