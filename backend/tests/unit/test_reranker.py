"""
The reranker (retrieval/reranker.py), with a fake cross-encoder in place of the model:

  - off (no model set): the search's own order, first k, and no model is loaded;
  - on: the k passages the model scores highest, best first, each with its "relevance";
  - a model that cannot be loaded is tried once, logged, and the search's order is used from
    then on; one that fails on a question gives that question the search's order;
  - startup loads the model in the background when one is set.
"""

import threading

import pytest
from fastapi.testclient import TestClient

from fakes import FakeCrossEncoder
from main import create_app
from src.core.config import settings
from src.retrieval import reranker

HITS = [
    {"text": "the cited study reached an accuracy of 94.9 percent", "meta": {"chunk_id": "a"}, "score": 0.71},
    {"text": "our results section", "meta": {"chunk_id": "b"}, "score": 0.70},
    {"text": "our model reached the highest accuracy of 83.7 percent", "meta": {"chunk_id": "c"}, "score": 0.65},
]


@pytest.fixture
def model(monkeypatch):
    """Reranking on, with a fake model that prefers passages saying 83.7; returns the fake."""
    fake = FakeCrossEncoder(prefer=("83.7",))
    loads = []
    monkeypatch.setattr(settings, "rerank_model", "fake/cross-encoder")
    monkeypatch.setattr(reranker, "_loaded", None)
    monkeypatch.setattr(reranker, "_failed", None)
    monkeypatch.setattr(reranker, "_load", lambda name: loads.append(name) or fake)
    fake.loads = loads
    return fake


def test_without_a_model_the_search_order_is_kept_and_nothing_is_loaded(monkeypatch):
    monkeypatch.setattr(settings, "rerank_model", "")
    monkeypatch.setattr(reranker, "_load", lambda name: pytest.fail("no model should be loaded"))
    assert not reranker.enabled()
    assert reranker.rerank("best accuracy", HITS, 2) == HITS[:2]
    reranker.warm()


def test_the_passages_the_model_scores_highest_come_first(model):
    ranked = reranker.rerank("what was the best accuracy", HITS, 2)
    assert [h["meta"]["chunk_id"] for h in ranked] == ["c", "a"]
    assert ranked[0]["relevance"] > ranked[1]["relevance"]
    assert ranked[0]["score"] == 0.65  # the similarity is kept: the confidence is still on its scale
    assert model.calls == [("what was the best accuracy", [h["text"] for h in HITS])]


def test_the_model_is_loaded_once(model):
    reranker.rerank("accuracy", HITS, 2)
    reranker.rerank("accuracy", HITS, 2)
    reranker.warm()
    assert model.loads == ["fake/cross-encoder"]


def test_one_passage_needs_no_model(model):
    assert reranker.rerank("accuracy", HITS[:1], 5) == HITS[:1]
    assert model.calls == []


def test_a_model_that_cannot_be_loaded_is_tried_once_then_the_search_order_is_used(monkeypatch, caplog):
    tries = []

    def unreachable(name):
        tries.append(name)
        raise OSError("no network")

    monkeypatch.setattr(settings, "rerank_model", "fake/missing")
    monkeypatch.setattr(reranker, "_loaded", None)
    monkeypatch.setattr(reranker, "_failed", None)
    monkeypatch.setattr(reranker, "_load", unreachable)
    with caplog.at_level("WARNING", logger="aether.errors"):
        assert reranker.rerank("accuracy", HITS, 2) == HITS[:2]
        assert reranker.rerank("accuracy", HITS, 2) == HITS[:2]
    assert tries == ["fake/missing"]
    assert not reranker.enabled()
    assert [r.getMessage() for r in caplog.records] == ["rerank_model_unavailable"]
    # Another model is tried afresh
    monkeypatch.setattr(settings, "rerank_model", "fake/other")
    assert reranker.enabled()


def test_a_model_that_fails_on_a_question_gives_it_the_search_order(model, monkeypatch, caplog):
    def broken(query, documents, **kwargs):
        raise RuntimeError("onnx error")

    monkeypatch.setattr(model, "rerank", broken)
    with caplog.at_level("WARNING", logger="aether.errors"):
        assert reranker.rerank("accuracy", HITS, 2) == HITS[:2]
    assert "rerank_failed" in [r.getMessage() for r in caplog.records]


def test_startup_loads_the_model_in_the_background(model, monkeypatch):
    warmed = threading.Event()
    monkeypatch.setattr(reranker, "warm", warmed.set)
    with TestClient(create_app()):
        assert warmed.wait(5)


def test_startup_loads_nothing_without_a_model(monkeypatch):
    monkeypatch.setattr(settings, "rerank_model", "")
    monkeypatch.setattr(reranker, "warm", lambda: pytest.fail("nothing to load"))
    with TestClient(create_app()):
        pass
