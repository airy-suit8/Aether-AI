"""
The reranker (retrieval/reranker.py), with a fake cross-encoder in place of the model:

  - off (no model set): the search's own order, first k, and no model is loaded;
  - on: the k passages the model scores highest, best first, each with its "relevance";
  - a model that cannot be loaded is tried once, logged, and the search's order is used from
    then on; one that fails on a question gives that question the search's order;
  - startup loads the model in the background when one is set.
"""

import hashlib
import re
import threading

import huggingface_hub
import pytest
from fastapi.testclient import TestClient

from fakes import FakeCrossEncoder
from main import create_app
from src.core.config import RERANK_PINS, Settings, settings
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


# ── The default model's files are pinned (D-072) ──────────────────────────────

def _files(folder, contents):
    for name, data in contents.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(data)
    return {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}


def test_the_default_model_is_pinned_to_a_commit_and_the_checksums_of_its_files():
    revision, checksums = RERANK_PINS[Settings.model_fields["rerank_model"].default]
    assert re.fullmatch(r"[0-9a-f]{40}", revision)
    assert {"onnx/model.onnx", "tokenizer.json"} <= set(checksums)
    assert all(re.fullmatch(r"[0-9a-f]{64}", digest) for digest in checksums.values())


def test_pinned_files_are_fetched_at_their_commit_and_checked(tmp_path, monkeypatch):
    checksums = _files(tmp_path, {"config.json": b"{}", "onnx/model.onnx": b"the weights measured"})
    calls = []
    monkeypatch.setattr(huggingface_hub, "snapshot_download", lambda **kwargs: calls.append(kwargs) or str(tmp_path))
    assert reranker._pinned_files("org/model", "a" * 40, checksums) == tmp_path
    assert calls[0]["repo_id"] == "org/model" and calls[0]["revision"] == "a" * 40
    assert sorted(calls[0]["allow_patterns"]) == sorted(checksums) and calls[0]["cache_dir"] == str(settings.model_dir)


def test_a_file_that_is_not_the_one_pinned_is_refused_and_the_search_order_used(tmp_path, monkeypatch, caplog):
    measured = _files(tmp_path / "measured", {"onnx/model.onnx": b"the weights measured"})
    _files(tmp_path, {"onnx/model.onnx": b"other weights"})
    monkeypatch.setattr(huggingface_hub, "snapshot_download", lambda **kwargs: str(tmp_path))
    with pytest.raises(reranker.ModelFilesChanged, match="onnx/model.onnx of org/model"):
        reranker._pinned_files("org/model", "b" * 40, measured)

    monkeypatch.setitem(RERANK_PINS, "org/model", ("b" * 40, measured))
    monkeypatch.setattr(settings, "rerank_model", "org/model")
    monkeypatch.setattr(reranker, "_loaded", None)
    monkeypatch.setattr(reranker, "_failed", None)
    with caplog.at_level("WARNING", logger="aether.errors"):
        assert reranker.rerank("accuracy", HITS, 2) == HITS[:2]
    assert "rerank_model_unavailable" in [r.getMessage() for r in caplog.records]


def test_a_model_with_no_pin_is_loaded_as_fastembed_finds_it(monkeypatch):
    import fastembed.rerank.cross_encoder as cross_encoder
    made = []
    monkeypatch.setattr(cross_encoder, "TextCrossEncoder", lambda **kwargs: made.append(kwargs) or "encoder")
    monkeypatch.setattr(huggingface_hub, "snapshot_download", lambda **kwargs: pytest.fail("no pin, no pinned download"))
    assert reranker._load("org/unpinned") == "encoder"
    assert made == [{"model_name": "org/unpinned", "cache_dir": str(settings.model_dir)}]
