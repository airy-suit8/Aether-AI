"""
The three search methods on the vector store (dense, BM25, hybrid) and the rank fusion in
search_hybrid. Known defects in BM25 and the fusion key (R3) are in test_known_defects.py.
"""

import pytest

from src.retrieval import retriever
from src.vectordb import vector_store

CORPUS = {
    "pumps.txt": "Centrifugal pumps need their impeller seals replaced every six months.",
    "valves.txt": "Butterfly valves are greased quarterly and pressure tested annually.",
    "fans.txt": "Cooling fans in the server room run continuously and are dusted weekly.",
    "belts.txt": "Conveyor belts are tensioned monthly by the night shift.",
}


@pytest.fixture(scope="module")
def user():
    """One user with four one-chunk documents in the real (temp) vector store."""
    user_id = 870001
    from langchain_core.documents import Document
    vector_store.store.add_documents(user_id, [
        Document(page_content=text, metadata={"source": name, "page": 1, "chunk_id": name})
        for name, text in CORPUS.items()
    ])
    return user_id


def _sources(hits):
    return [h["meta"]["source"] for h in hits]


# ── Dense ─────────────────────────────────────────────────────────────────────

def test_dense_search_ranks_the_relevant_chunk_first(user):
    hits = retriever.retriever.search(user, "When are impeller seals on centrifugal pumps replaced?", k=4)
    assert _sources(hits)[0] == "pumps.txt"
    scores = [h["score"] for h in hits]
    assert scores == sorted(scores, reverse=True)
    assert all(0.0 <= s <= 1.0 + 1e-6 for s in scores)
    assert hits[0]["text"] == CORPUS["pumps.txt"]


def test_dense_search_returns_at_most_k(user):
    assert len(retriever.retriever.search(user, "maintenance", k=2)) == 2


def test_dense_search_for_a_user_with_no_documents_is_empty():
    assert retriever.retriever.search(870099, "pumps", k=5) == []


# ── BM25 ──────────────────────────────────────────────────────────────────────

def test_bm25_ranks_the_keyword_match_first(user):
    hits = retriever.retriever.search_bm25(user, "butterfly valves greased", k=4)
    assert _sources(hits)[0] == "valves.txt"
    assert all(h["score"] > 0 for h in hits)


def test_bm25_returns_only_chunks_that_share_a_word(user):
    assert retriever.retriever.search_bm25(user, "xylophone quasar", k=4) == []


def test_bm25_respects_k(user):
    assert len(retriever.retriever.search_bm25(user, "are the and by", k=1)) == 1


def test_bm25_for_a_user_with_no_documents_is_empty():
    assert retriever.retriever.search_bm25(870099, "pumps", k=5) == []


def test_bm25_swallows_store_errors(user, monkeypatch):
    # Today any error returns an empty list (R3 notes this hides failures)
    monkeypatch.setattr(type(vector_store.store.chroma._collection), "get",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk")))
    assert retriever.retriever.search_bm25(user, "pumps", k=4) == []


# ── Hybrid, through the real store ────────────────────────────────────────────

def test_hybrid_search_puts_the_chunk_both_methods_agree_on_first(user):
    hits = retriever.retriever.search_hybrid(user, "conveyor belts tensioned monthly", k=3)
    assert _sources(hits)[0] == "belts.txt"
    assert hits[0]["score"] == 1.0  # ranked first by both: the maximum fused score
    assert len(hits) <= 3


# ── Fusion arithmetic, with the two inputs fixed ──────────────────────────────

def _hit(text, score=0.5):
    return {"text": text, "meta": {"source": f"{text}.txt", "chunk_id": text}, "score": score}


@pytest.fixture
def fused(monkeypatch):
    """search_hybrid on a store whose dense and BM25 results are set by the test."""
    store = retriever.Retriever(vector_store.store)

    def run(dense, bm25, k=5, rrf_k=60):
        monkeypatch.setattr(store, "search", lambda user_id, query, k: dense[:k])
        monkeypatch.setattr(store, "search_bm25", lambda user_id, query, k: bm25[:k])
        return store.search_hybrid(1, "q", k=k, rrf_k=rrf_k)

    return run


def test_fusion_rewards_agreement(fused):
    dense = [_hit("a"), _hit("b"), _hit("c")]
    bm25 = [_hit("c"), _hit("d")]
    hits = fused(dense, bm25)
    # c: 1/63 + 1/61, a: 1/61, d: 1/62, b: 1/62 — c first, then a, then b and d tied
    assert [h["text"] for h in hits][:2] == ["c", "a"]
    assert {h["text"] for h in hits} == {"a", "b", "c", "d"}


def test_fusion_scores_are_normalised_to_the_best_possible(fused):
    hits = fused([_hit("a"), _hit("b")], [_hit("a"), _hit("x")])
    by_text = {h["text"]: h["score"] for h in hits}
    assert by_text["a"] == 1.0                          # first in both lists
    assert by_text["b"] == round((1 / 62) / (2 / 61), 3)  # second in one list only
    assert by_text["x"] == by_text["b"]


def test_fusion_score_has_a_floor_of_point_one(fused):
    # With rrf_k=1, rank r in one list scores (1/(1+r)) / (2/2): below 0.1 from rank 10 on
    hits = fused([_hit(f"d{i}") for i in range(12)], [_hit("b")], k=13, rrf_k=1)
    by_text = {h["text"]: h["score"] for h in hits}
    assert by_text["d0"] == 0.5
    assert by_text["d9"] == 0.1 and by_text["d11"] == 0.1


def test_fusion_returns_at_most_k(fused):
    hits = fused([_hit(t) for t in "abcdef"], [_hit(t) for t in "ghij"], k=3)
    assert len(hits) == 3


def test_fusion_does_not_change_the_input_hits(fused):
    dense = [_hit("a", score=0.42)]
    fused(dense, [_hit("a", score=7.0)])
    assert dense[0]["score"] == 0.42


@pytest.mark.parametrize("dense,bm25,expected", [
    ([], [], []),
    ([_hit("a", 0.8), _hit("b", 0.7)], [], ["a", "b"]),
    ([], [_hit("c", 3.2)], ["c"]),
])
def test_fusion_falls_back_when_one_side_is_empty(fused, dense, bm25, expected):
    hits = fused(dense, bm25)
    assert [h["text"] for h in hits] == expected
    # The fallback keeps the original scores (a different scale from fused scores, R3)
    assert [h["score"] for h in hits] == [h["score"] for h in (dense or bm25)]


# ── The LangChain retriever object (Task 14) ──────────────────────────────────

def test_user_retriever_is_a_langchain_retriever_over_the_dense_search(user):
    from langchain_core.retrievers import BaseRetriever
    lc = retriever.UserRetriever(user_id=user, k=2)
    assert isinstance(lc, BaseRetriever)
    docs = lc.invoke("When are impeller seals on centrifugal pumps replaced?")
    dense = retriever.retriever.search(user, "When are impeller seals on centrifugal pumps replaced?", k=2)
    assert [d.page_content for d in docs] == [h["text"] for h in dense]
    assert [d.metadata["score"] for d in docs] == [h["score"] for h in dense]
    assert retriever.UserRetriever(user_id=870099, k=2).invoke("pumps") == []
