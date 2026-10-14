"""
Reranking through the API (retrieval/reranker.py, pipeline/rag.py), with the fake embeddings and a
fake cross-encoder. The paper is like the owner's: its literature review quotes a cited study's
accuracy in the words of the question, and its own result comes later, in other words. The
search alone puts the cited study first; the reranker, which here prefers the paper's own
figure, puts that first, and the model is given it.

  - every mode's search is reranked, from rerank_candidates passages down to top_k;
  - a question about each document reranks each one's passages, the candidates shared out;
  - with no reranking model, or one that cannot be loaded, the search's order answers.
"""

import pytest

from fakes import FakeCrossEncoder
from filemakers import make_pdf
from helpers import ask
from src.core.config import settings
from src.retrieval import reranker

PAGES = [
    "Classification of maternal health risks using boosting. Abstract: boosting classifies risk.",
    "Literature: a cited study reported that a hybrid model reached the highest accuracy of 94.9 percent.",
    "Methodology: the dataset was split into training and testing sets.",
    "Results: our XGBoost classifier reached the highest accuracy of 83.7 percent in Table 4.",
    "Discussion: gradient boosting handles numerical features well.",
    "Conclusion: boosting can classify maternal health risks.",
]
QUESTION = "Which model reached the highest accuracy reported?"


@pytest.fixture
def paper(client, make_user, tmp_path, monkeypatch):
    """A user with the paper, one passage read per question (top_k 1, no neighbours), nothing
    refused for the fake embeddings' low scores. Returns their headers."""
    monkeypatch.setattr(settings, "top_k", 1)
    monkeypatch.setattr(settings, "chunk_window", 0)
    monkeypatch.setattr(settings, "confidence_threshold", 0.0)
    _, headers = make_user("rerank")
    pdf = make_pdf(tmp_path / "13003-64313-1-PB.pdf", PAGES)
    r = client.post("/api/v1/upload", headers=headers, files={"file": (pdf.name, pdf.read_bytes(), "application/pdf")})
    assert r.status_code == 202, r.text
    return headers


@pytest.fixture
def cross_encoder(monkeypatch):
    """Reranking on, with a fake model that prefers the paper's own figure; returns the fake."""
    fake = FakeCrossEncoder(prefer=("83.7",))
    monkeypatch.setattr(settings, "rerank_model", "fake/cross-encoder")
    monkeypatch.setattr(settings, "rerank_candidates", 4)
    monkeypatch.setattr(reranker, "_loaded", None)
    monkeypatch.setattr(reranker, "_failed", None)
    monkeypatch.setattr(reranker, "_load", lambda name: fake)
    return fake


def _read(fake_llm):
    """The passages the answering model was given."""
    return fake_llm.prompts[-1]


def test_without_reranking_the_search_puts_the_cited_study_first(client, paper, fake_llm):
    assert ask(client, paper, QUESTION).status_code == 200
    assert "94.9" in _read(fake_llm) and "83.7" not in _read(fake_llm)


@pytest.mark.parametrize("mode", ["default", "hybrid", "langchain"])
def test_the_reranker_puts_the_papers_own_result_first_in_every_mode(client, paper, cross_encoder, fake_llm, mode):
    r = ask(client, paper, QUESTION, mode=mode)
    assert r.status_code == 200, r.text
    assert "83.7" in _read(fake_llm) and "94.9" not in _read(fake_llm)
    # It read the candidates the search found, not only the one kept
    question, passages = cross_encoder.calls[-1]
    assert question == QUESTION and len(passages) == 4
    assert [s["page"] for s in r.json()["sources"]] == [4]


def test_the_agents_document_search_is_reranked(client, paper, cross_encoder, fake_llm):
    r = ask(client, paper, "Search the documents: " + QUESTION, mode="agent")
    assert r.status_code == 200, r.text
    assert cross_encoder.calls, "the agent's search went through the reranker"


def test_a_question_about_each_document_reranks_each_ones_passages(client, paper, cross_encoder, fake_llm, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "top_k", 2)
    second = make_pdf(tmp_path / "second.pdf", ["Results: the second paper reached an accuracy of 71 percent.",
                                                "Its conclusion repeats the accuracy."])
    r = client.post("/api/v1/upload", headers=paper, files={"file": (second.name, second.read_bytes(), "application/pdf")})
    assert r.status_code == 202
    cross_encoder.calls.clear()
    assert ask(client, paper, "What accuracy does each paper report?").status_code == 200
    # One call per document, each with its share of the candidates (4 between 2) or fewer
    assert len(cross_encoder.calls) == 2
    assert all(len(passages) <= 2 for _, passages in cross_encoder.calls)


def test_a_model_that_cannot_be_loaded_leaves_the_search_order(client, paper, fake_llm, monkeypatch):
    def unreachable(name):
        raise OSError("no network")

    monkeypatch.setattr(settings, "rerank_model", "fake/missing")
    monkeypatch.setattr(reranker, "_loaded", None)
    monkeypatch.setattr(reranker, "_failed", None)
    monkeypatch.setattr(reranker, "_load", unreachable)
    r = ask(client, paper, QUESTION)
    assert r.status_code == 200, r.text
    assert "94.9" in _read(fake_llm)
