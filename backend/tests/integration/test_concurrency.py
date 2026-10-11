"""A slow model call must not stall the server: /health answers while chats are running (B11)."""

import threading
import time

from helpers import upload_text, ask, ask_stream

SLOW = 2.0  # seconds per fake model call
QUESTION = "How often is the Zephyr turbine blade inspection?"


def _time_health_while(client, start_request):
    """Start a slow request in a thread, then time /health while it is still running."""
    worker = threading.Thread(target=start_request)
    worker.start()
    time.sleep(0.5)  # let the slow request reach the model
    assert worker.is_alive(), "the slow request finished too early to test anything"
    t0 = time.perf_counter()
    r = client.get("/api/v1/health")
    health_seconds = time.perf_counter() - t0
    worker.join()
    assert r.status_code == 200
    return health_seconds


def test_health_is_not_blocked_by_slow_chat(client, make_user, fake_llm):
    _, headers = make_user("slow")
    upload_text(client, headers)
    fake_llm.delay = SLOW
    results = []
    seconds = _time_health_while(client, lambda: results.append(ask(client, headers, QUESTION)))
    assert "90 days" in results[0].json()["answer"]
    assert seconds < 1.0, f"/health took {seconds:.2f}s while a chat was running"


def test_health_is_not_blocked_by_slow_stream(client, make_user, fake_llm):
    _, headers = make_user("slows")
    upload_text(client, headers)
    fake_llm.delay = SLOW
    results = []
    seconds = _time_health_while(client, lambda: results.append(ask_stream(client, headers, QUESTION)))
    assert results[0][1][-1]["type"] == "done" and results[0][1][-1]["sources"]
    assert seconds < 1.0, f"/health took {seconds:.2f}s while a stream was running"


def test_two_chats_run_at_the_same_time(client, make_user, fake_llm):
    _, headers = make_user("pair")
    upload_text(client, headers)
    fake_llm.delay = SLOW
    # Each chat makes two model calls (summarize, answer), so one chat takes about 2 * SLOW.
    results = []
    threads = [threading.Thread(target=lambda s=s: results.append(ask(client, headers, QUESTION, session_id=s)))
               for s in ("p1", "p2")]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - t0
    assert all("90 days" in r.json()["answer"] for r in results) and len(results) == 2
    assert elapsed < 3 * SLOW, f"two chats took {elapsed:.1f}s; they ran one after the other"
