"""LangChain mode (Tasks 12-15) must answer, and keep each user's history separate (B1)."""

from helpers import upload_text, ask, ask_stream

QUESTION = "How often is the Zephyr turbine blade inspection?"


def test_langchain_chat_answers_with_citation(client, make_user):
    _, headers = make_user("lc")
    assert upload_text(client, headers).status_code == 202

    r = ask(client, headers, QUESTION, mode="langchain")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "90 days" in body["answer"]
    assert body["sources"][0]["source"] == "zephyr_manual.txt"


def test_langchain_stream_answers(client, make_user):
    _, headers = make_user("lcs")
    assert upload_text(client, headers).status_code == 202

    status, events = ask_stream(client, headers, QUESTION, mode="langchain")
    assert status == 200
    assert [e["type"] for e in events][-1] == "done"
    assert "90 days" in "".join(e["content"] for e in events if e["type"] == "token")
    assert events[-1]["sources"][0]["source"] == "zephyr_manual.txt"


def test_langchain_history_is_scoped_to_the_user(client, make_user, fake_llm):
    _, alice = make_user("alice")
    _, bob = make_user("bob")
    upload_text(client, alice)
    upload_text(client, bob)

    # Same session id for both users: Bob must not see Alice's turn in his history.
    assert ask(client, alice, "Alice secret question about Zephyr turbine?", session_id="shared", mode="langchain").status_code == 200
    fake_llm.prompts.clear()
    assert ask(client, bob, QUESTION, session_id="shared", mode="langchain").status_code == 200
    assert not any("Alice secret question" in p for p in fake_llm.prompts)


def test_only_langchain_mode_retrieves_through_the_langchain_retriever(client, make_user, monkeypatch):
    # Decision 5: the LangChain strategy genuinely differs, it does not just relabel the default
    from src.retrieval.retriever import UserRetriever

    calls = []
    original = UserRetriever._get_relevant_documents

    def spy(self, query, *, run_manager):
        calls.append(query)
        return original(self, query, run_manager=run_manager)

    monkeypatch.setattr(UserRetriever, "_get_relevant_documents", spy)
    _, headers = make_user("lcret")
    upload_text(client, headers)
    assert ask(client, headers, QUESTION, session_id="d").status_code == 200
    assert calls == []
    assert ask(client, headers, QUESTION, session_id="l", mode="langchain").status_code == 200
    assert calls == [QUESTION]
