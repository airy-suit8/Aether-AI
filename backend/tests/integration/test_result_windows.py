"""
A paper's own results come with the passages either side (pipeline/rag.py, D-078). Besides the two
best hits, a passage the search found in a results, discussion or conclusion section gets its
neighbours too, so a best figure one passage away from the one found reaches the model.

The search is replaced by one that "finds" chosen passages in a chosen order, so the test does not
depend on how the fake embeddings happen to score them; the passages are the uploaded paper's own.
"""

import pytest

from filemakers import make_pdf
from helpers import status_of, tenant_of, user_id_of
from src.core.config import settings
from src.pipeline import rag
from src.vectordb.vector_store import store

PAGES = [
    "Classification of maternal health risks\nABSTRACT\nBoosting classifies the risk.",
    "INTRODUCTION\nA cited hybrid model reached the highest accuracy of 94.9% [5].",
    "LITERATURE STUDY\nA boosted random forest reached a testing accuracy of 97.03%.",
    "The data were split three ways for the experiments.",
    "RESULTS\nThe XGBoost classifier has the highest result of accuracy by 84%.",
    "The accuracy rate of the 80:20 splitting size is 82.73%.",
    "CONCLUSION\nBoosting can classify maternal health risks.",
]


@pytest.fixture
def paper(client, make_user, tmp_path, monkeypatch):
    """A user with the paper (one passage a page, numbered from 1), the chunk window on, and a
    search that finds the passages the test names, best first. Returns (user id, document id, find)."""
    monkeypatch.setattr(settings, "chunk_window", 1)
    _, headers = make_user("results")
    pdf = make_pdf(tmp_path / "paper.pdf", PAGES)
    record = status_of(client, headers, client.post(
        "/api/v1/upload", headers=headers, files={"file": (pdf.name, pdf.read_bytes(), "application/pdf")}))
    assert record["status"] == "ready", record
    tenant, document_id = tenant_of(headers), record["id"]

    def find(*numbers):
        found = []
        for rank, number in enumerate(numbers):
            (text, meta), = store.passages_at(tenant, document_id, [number])
            found.append({"text": text, "meta": meta, "score": 0.5, "relevance": 10.0 - rank})
        monkeypatch.setattr(rag, "_search", lambda *args, **kwargs: list(found))

    return user_id_of(headers), document_id, find


def _numbers(hits):
    return [h["meta"]["chunk_index"] for h in hits]


def test_a_result_found_third_brings_the_passage_with_the_best_figure(paper):
    user_id, _, find = paper
    find(2, 3, 6)  # the introduction and the literature study first, the paper's own result third
    hits = rag.retrieve("default", user_id, "What is the best accuracy?")
    assert _numbers(hits) == [1, 2, 3, 4, 5, 6, 7]
    assert any("by 84%" in h["text"] for h in hits)
    assert [h.get("added") for h in hits if h["meta"]["chunk_index"] in (5, 7)] == ["neighbour", "neighbour"]


def test_without_it_only_the_two_best_have_neighbours(paper, monkeypatch):
    user_id, _, find = paper
    monkeypatch.setattr(rag, "_result_windows", lambda tenant, hits: [])
    find(2, 3, 6)
    hits = rag.retrieve("default", user_id, "What is the best accuracy?")
    assert _numbers(hits) == [1, 2, 3, 4, 6]
    assert not any("by 84%" in h["text"] for h in hits)


def test_a_passage_found_third_outside_the_results_gets_no_neighbours(paper):
    user_id, _, find = paper
    find(5, 6, 2)  # the introduction third: its neighbours (1, 3) are not added
    assert _numbers(rag.retrieve("default", user_id, "What is the best accuracy?")) == [2, 4, 5, 6, 7]


@pytest.mark.parametrize("section, gets_window", [
    ("Results", True),
    ("Discussion, then Conclusion", True),
    ("Implementation and results", True),
    ("Introduction, then Literature study", False),
    ("Methodology", False),
    ("", False),
])
def test_which_sections_are_a_paper_s_own_results(section, gets_window):
    hit = {"text": "x", "meta": {"section": section} if section else {}, "score": 0.5}
    assert (rag._result_windows("tenant", [hit]) == [hit]) is gets_window
