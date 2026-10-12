"""
The sources shown with an answer (R5): none for a refusal, and, when the answer is written from
numbered chunks (settings.answer_from = "chunks"), exactly the chunks it cites.
"""

import uuid

import pytest
from langchain_core.messages import AIMessage

from fakes import ScriptedChatModel
from helpers import DOC_TEXT, upload_text, ask, ask_stream
from src.core.config import settings
from src.db.database import create_user
from src.pipeline import rag

QUESTION = "How often is the Zephyr turbine blade inspection?"
REFUSAL = "I could not find relevant information in the uploaded documents."
MODES = [{}, {"mode": "hybrid"}, {"mode": "langchain"}]
MODE_IDS = ["default", "hybrid", "langchain"]


@pytest.fixture
def refusing_model(monkeypatch):
    """A model that refuses every question, although retrieval passed the threshold."""
    original = ScriptedChatModel._reply

    def reply(self, messages):
        if "Answer:" in str(messages[-1].content) and "Standalone Question:" not in str(messages[-1].content):
            return AIMessage(content=REFUSAL)
        return original(self, messages)

    monkeypatch.setattr(ScriptedChatModel, "_reply", reply)


@pytest.fixture
def from_chunks(monkeypatch):
    monkeypatch.setattr(settings, "answer_from", "chunks")


@pytest.fixture
def two_documents(client, make_user):
    _, headers = make_user("cite")
    upload_text(client, headers, text=DOC_TEXT)
    upload_text(client, headers, filename="halcyon.txt",
                text="The Halcyon register is the log of every Zephyr turbine blade inspection.")
    return headers


# ── A refusal used no passage ─────────────────────────────────────────────────

@pytest.mark.parametrize("modes", MODES, ids=MODE_IDS)
def test_refused_answer_lists_no_sources(client, make_user, refusing_model, modes):
    # Was a known defect: a refused answer listed every retrieved chunk as a source
    _, headers = make_user("refuse")
    upload_text(client, headers, text=DOC_TEXT)
    r = ask(client, headers, QUESTION, **modes)
    assert r.json()["answer"] == REFUSAL
    assert r.json()["sources"] == []


def test_refused_streamed_answer_lists_no_sources(client, make_user, refusing_model):
    _, headers = make_user("refuses")
    upload_text(client, headers, text=DOC_TEXT)
    _, events = ask_stream(client, headers, QUESTION)
    assert "".join(e["content"] for e in events if e["type"] == "token") == REFUSAL
    assert events[-1]["sources"] == []


@pytest.mark.parametrize("answer,refused", [
    (REFUSAL, True),
    ("  I could not find relevant information in the uploaded documents to answer that question.", True),
    (rag.NO_DOCUMENTS, True),
    ("The blades are inspected every 90 days.", False),
    ("The manual says: I could not find relevant information.", False),
])
def test_a_refusal_is_recognised_by_how_it_starts(answer, refused):
    assert rag.is_refusal(answer) is refused


# ── By default the answer comes from a summary, and every retrieved page is listed ─

@pytest.mark.parametrize("modes", MODES, ids=MODE_IDS)
def test_by_default_the_answer_is_written_from_a_summary(two_documents, client, fake_llm, modes):
    r = ask(client, two_documents, QUESTION, **modes)
    assert sorted(s["source"] for s in r.json()["sources"]) == ["halcyon.txt", "zephyr_manual.txt"]
    assert all("number" not in s for s in r.json()["sources"])
    assert any("Focused Summary:" in p for p in fake_llm.prompts)
    assert not any('<document number="' in p for p in fake_llm.prompts)


# ── Written from numbered chunks: the sources are the chunks cited ────────────

@pytest.mark.parametrize("modes", MODES, ids=MODE_IDS)
def test_an_answer_from_chunks_lists_only_the_chunk_it_cites(two_documents, client, fake_llm, from_chunks, modes):
    r = ask(client, two_documents, QUESTION, **modes)
    body = r.json()
    assert body["answer"].endswith("[1]")
    # One model call, on the numbered chunks: no summary step
    assert len(fake_llm.prompts) == 1 and "Focused Summary:" not in fake_llm.prompts[0]
    assert '<document number="1" source=' in fake_llm.prompts[0] and '<document number="2" source=' in fake_llm.prompts[0]
    # Two chunks were retrieved; only the one cited is a source, and it carries its number
    assert [s["number"] for s in body["sources"]] == [1]
    assert f'<document number="1" source="{body["sources"][0]["source"]}"' in fake_llm.prompts[0]
    assert set(body["sources"][0]) == {"number", "source", "page", "snippet", "score"}


def test_citations_of_numbers_that_were_not_offered_are_ignored(two_documents, client, fake_llm, from_chunks):
    fake_llm.citations = "[2][2] and [7], [0], [x]"
    sources = ask(client, two_documents, QUESTION).json()["sources"]
    assert [s["number"] for s in sources] == [2]


def test_an_answer_that_cites_nothing_lists_every_page_retrieved(two_documents, client, fake_llm, from_chunks):
    fake_llm.citations = ""
    sources = ask(client, two_documents, QUESTION).json()["sources"]
    assert sorted(s["source"] for s in sources) == ["halcyon.txt", "zephyr_manual.txt"]


def test_a_streamed_answer_from_chunks_ends_with_its_cited_sources(two_documents, client, from_chunks):
    _, events = ask_stream(client, two_documents, QUESTION)
    assert [s["number"] for s in events[-1]["sources"]] == [1]


def test_a_refusal_from_chunks_lists_no_sources(two_documents, client, refusing_model, from_chunks):
    assert ask(client, two_documents, QUESTION).json()["sources"] == []


def test_cited_numbers_are_sorted_unique_and_within_range():
    assert rag.cited_numbers("Stated in [3] and [1][3]; not [9], [0] or [two].", available=3) == [1, 3]
    assert rag.cited_numbers("No citations here.", available=3) == []


def test_a_question_with_no_documents_is_traced_as_refused_after_retrieval_only(from_chunks):
    trace = rag.Trace()
    user_id = create_user(f"nodocs_{uuid.uuid4().hex[:8]}", "hash")
    result = rag.answer(user_id, "anything", session_id="none", trace=trace)
    assert result["answer"] == rag.NO_DOCUMENTS and trace.refused and trace.hits == []
    assert list(trace.stages) == ["retrieve"]
