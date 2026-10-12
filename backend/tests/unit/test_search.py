"""
The three search methods (dense, BM25, hybrid), the rank fusion in search_hybrid, and the
score every one of them reports: cosine similarity from 0 to 1 (R2, R3).
"""

import uuid

import pytest
from langchain_core.documents import Document

from src.core.config import settings
from src.db import database
from src.pipeline import rag
from src.retrieval import retriever
from src.vectordb import vector_store

CORPUS = {
    "pumps.txt": "Centrifugal pumps need their impeller seals replaced every six months.",
    "valves.txt": "Butterfly valves are greased quarterly and pressure tested annually.",
    "fans.txt": "Cooling fans in the server room run continuously and are dusted weekly.",
    "belts.txt": "Conveyor belts are tensioned monthly by the night shift.",
}


@pytest.fixture(scope="module", autouse=True)
def own_store(tmp_path_factory):
    """
    A vector store of this module's own, restored afterwards. These tests compare exact search
    results, and the shared test store holds the same text many times over (most tests upload
    the same file for a new user). Over many identical vectors Chroma's filtered HNSW search can
    miss a tenant's chunks, which made these tests fail now and then once the suite grew.
    """
    store = vector_store.store
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "vector_store_dir", tmp_path_factory.mktemp("search_store"))
        for opened in ("_client", "_collection", "_chroma"):  # reopened at the new path on first use
            mp.setattr(store, opened, None)
        yield store


@pytest.fixture(scope="module")
def owner(own_store):
    """One user, (user id, tenant id), with four one-chunk documents in a vector store of its own."""
    user_id = database.create_user(f"search_{uuid.uuid4().hex[:8]}", "hash")
    tenant = database.get_tenant_id(user_id)
    vector_store.store.add_documents(tenant, [
        Document(page_content=text, metadata={"source": name, "page": 1, "chunk_id": name})
        for name, text in CORPUS.items()
    ])
    return user_id, tenant


@pytest.fixture(scope="module")
def user(owner):
    """That user's tenant id, the key the searches take."""
    return owner[1]


def _sources(hits):
    return [h["meta"]["source"] for h in hits]


# ── Dense ─────────────────────────────────────────────────────────────────────

def test_dense_search_ranks_the_relevant_chunk_first(user):
    hits = retriever.retriever.search(user, "When are impeller seals on centrifugal pumps replaced?", k=4)
    assert _sources(hits)[0] == "pumps.txt"
    scores = [h["score"] for h in hits]
    assert scores == sorted(scores, reverse=True)
    assert all(0.0 <= s <= 1.0 for s in scores)
    assert hits[0]["text"] == CORPUS["pumps.txt"]


def test_dense_search_returns_at_most_k(user):
    assert len(retriever.retriever.search(user, "maintenance", k=2)) == 2


def test_dense_search_for_a_user_with_no_documents_is_empty():
    assert retriever.retriever.search("tenant-870099", "pumps", k=5) == []


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
    assert retriever.retriever.search_bm25("tenant-870099", "pumps", k=5) == []


def test_bm25_reports_store_errors(user, monkeypatch):
    # R3: an error used to be swallowed and returned as "no results"
    fresh = retriever.Retriever(vector_store.store)  # nothing cached, so it must read the store
    monkeypatch.setattr(type(vector_store.store.chroma._collection), "get",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk")))
    with pytest.raises(RuntimeError, match="disk"):
        fresh.search_bm25(user, "pumps", k=4)


def _add_chunks(tenant, texts):
    vector_store.store.add_documents(tenant, [
        Document(page_content=t, metadata={"source": f"doc{i}.txt", "page": 1, "chunk_id": f"{tenant}-{i}"})
        for i, t in enumerate(texts)
    ])


def test_bm25_finds_the_only_chunk():
    # R3: with rank_bm25's own idf, a word in the user's only chunk scored below zero
    _add_chunks(860001, ["The north gate opens at six every morning"])
    assert retriever.retriever.search_bm25(860001, "north gate", k=5)


def test_bm25_finds_one_of_two_chunks():
    # R3: a word in one of two chunks had an idf of exactly zero
    _add_chunks(860002, ["The north gate opens at six every morning", "Lunch is served in the canteen"])
    hits = retriever.retriever.search_bm25(860002, "gate", k=5)
    assert [h["meta"]["source"] for h in hits] == ["doc0.txt"]


SIGNS = [
    "Visitors sign in at the gate.",
    "Lunch is served in the canteen at noon",
    "The car park closes at nine at night",
    "Fire drills happen on the first Monday",
]


def test_bm25_matches_a_word_next_to_punctuation():
    # R3: the tokenizer was lower().split(), so "gate" never matched "gate."
    _add_chunks(860004, SIGNS)
    assert _sources(retriever.retriever.search_bm25(860004, "canteen", k=5)) == ["doc1.txt"]
    assert _sources(retriever.retriever.search_bm25(860004, "gate", k=5)) == ["doc0.txt"]
    assert _sources(retriever.retriever.search_bm25(860004, "Gate?", k=5)) == ["doc0.txt"]


def test_bm25_index_is_built_once_and_rebuilt_when_the_chunks_change(monkeypatch):
    # R3: the index was rebuilt from every chunk on every query
    reads = []
    real = vector_store.store.get_user_chunks
    monkeypatch.setattr(vector_store.store, "get_user_chunks", lambda tenant: reads.append(tenant) or real(tenant))
    fresh, tenant = retriever.Retriever(vector_store.store), "tenant-860005"

    _add_chunks(tenant, ["Forklifts are charged overnight"])
    assert fresh.search_bm25(tenant, "forklifts", k=5) and fresh.search_bm25(tenant, "charged", k=5)
    assert reads == [tenant]

    vector_store.store.add_documents(tenant, [
        Document(page_content="Pallet jacks are inspected weekly", metadata={"source": "new.txt", "page": 1, "chunk_id": "tenant-860005-new"})])
    assert _sources(fresh.search_bm25(tenant, "pallet jacks", k=5)) == ["new.txt"]  # an upload is seen at once
    assert reads == [tenant, tenant]

    vector_store.store.delete_user_chunks(tenant)
    assert fresh.search_bm25(tenant, "forklifts", k=5) == []                          # and so is a delete


def test_bm25_keeps_the_index_of_only_the_most_recent_users(monkeypatch):
    monkeypatch.setattr(retriever, "BM25_USERS_KEPT", 2)
    fresh = retriever.Retriever(vector_store.store)
    for tenant in ("tenant-860011", "tenant-860012", "tenant-860013"):
        fresh.search_bm25(tenant, "anything", k=1)
    assert list(fresh._bm25) == ["tenant-860012", "tenant-860013"]


# ── Hybrid, through the real store ────────────────────────────────────────────

def test_hybrid_search_puts_the_chunk_both_methods_agree_on_first(user):
    question = "conveyor belts tensioned monthly"
    hits = retriever.retriever.search_hybrid(user, question, k=3)
    assert _sources(hits)[0] == "belts.txt"
    # R2: the score is the chunk's cosine similarity, as in dense search, not a rank value
    assert hits[0]["score"] == retriever.retriever.search(user, question, k=1)[0]["score"]
    assert len(hits) <= 3


def test_a_chunk_only_the_keyword_search_finds_gets_its_similarity(user, monkeypatch):
    question = "When are impeller seals on centrifugal pumps replaced?"
    dense_all = {h["meta"]["chunk_id"]: h["score"] for h in retriever.retriever.search(user, question, k=4)}
    fresh = retriever.Retriever(vector_store.store)
    monkeypatch.setattr(fresh, "search", lambda tenant, query, k: [])  # dense search finds nothing
    hits = fresh.search_hybrid(user, question, k=4)
    assert _sources(hits)[0] == "pumps.txt"
    for hit in hits:
        assert hit["score"] == pytest.approx(dense_all[hit["meta"]["chunk_id"]], abs=1e-6)


@pytest.mark.parametrize("mode", ["default", "hybrid", "langchain"])
def test_an_off_topic_question_is_refused_in_every_mode_without_asking_the_model(owner, fake_llm, mode):
    # R2: in hybrid mode the rank-based score could not fall below 0.44, so nothing was refused
    result = rag.answer(owner[0], "xylophone quasar", session_id=f"offtopic-{mode}", mode=mode)
    assert result["answer"] == rag.NOT_FOUND and result["sources"] == []
    assert result["confidence"] < settings.confidence_threshold
    assert fake_llm.prompts == []


def test_scores_never_pass_one(user):
    # An exact match used to score 1.0000002, which made LangChain print a warning with the chunk text
    hits = retriever.retriever.search(user, CORPUS["pumps.txt"], k=4)
    assert hits[0]["score"] <= 1.0 and hits[0]["score"] == pytest.approx(1.0)
    assert all(0.0 <= h["score"] <= 1.0 for h in hits)


def test_similarities_are_cosines_of_the_named_chunks_of_that_user_only(user):
    question = "When are impeller seals on centrifugal pumps replaced?"
    dense = {h["meta"]["chunk_id"]: h["score"] for h in retriever.retriever.search(user, question, k=4)}
    found = vector_store.store.similarities(user, question, ["pumps.txt", "fans.txt", "no-such-chunk"])
    assert found == {key: pytest.approx(dense[key], abs=1e-6) for key in ("pumps.txt", "fans.txt")}
    assert vector_store.store.similarities("tenant-870099", question, ["pumps.txt"]) == {}  # another user's chunk
    assert vector_store.store.similarities(user, question, []) == {}


# ── Fusion arithmetic, with the two inputs fixed ──────────────────────────────

def _hit(text, score=0.5):
    return {"text": text, "meta": {"source": f"{text}.txt", "chunk_id": text}, "score": score}


@pytest.fixture
def fused(monkeypatch):
    """search_hybrid on a store whose dense and BM25 results, and similarities, are set by the test."""
    store = retriever.Retriever(vector_store.store)
    monkeypatch.setattr(vector_store.store, "similarities", lambda tenant, query, chunk_ids: {c: 0.33 for c in chunk_ids})

    def run(dense, bm25, k=5, rrf_k=60):
        monkeypatch.setattr(store, "search", lambda tenant, query, k: dense[:k])
        monkeypatch.setattr(store, "search_bm25", lambda tenant, query, k: bm25[:k])
        return store.search_hybrid(1, "q", k=k, rrf_k=rrf_k)

    return run


def test_fusion_rewards_agreement(fused):
    dense = [_hit("a"), _hit("b"), _hit("c")]
    bm25 = [_hit("c"), _hit("d")]
    hits = fused(dense, bm25)
    # c: 1/63 + 1/61, a: 1/61, d: 1/62, b: 1/62 — c first, then a, then b and d tied
    assert [h["text"] for h in hits][:2] == ["c", "a"]
    assert {h["text"] for h in hits} == {"a", "b", "c", "d"}


def test_fusion_keeps_different_chunks_that_share_an_opening(fused):
    # R3: the fusion key was text[:120], so chunks that opened the same way were merged
    opening = "Section 4.2 Safety. " + "All maintenance staff must follow the lockout procedure. " * 2
    assert len(opening) > 120
    first = {"text": opening + "Applies to turbines.", "meta": {"chunk_id": "c1", "source": "a.txt"}, "score": 0.9}
    second = {"text": opening + "Applies to pumps.", "meta": {"chunk_id": "c2", "source": "a.txt"}, "score": 0.8}
    hits = fused([first, second], [second])
    assert sorted(h["meta"]["chunk_id"] for h in hits) == ["c1", "c2"]


def test_fused_hits_are_scored_by_similarity_not_by_rank(fused):
    # R2: a and b keep their dense similarity; x, found by keywords only, gets its own looked up
    hits = fused([_hit("a", 0.9), _hit("b", 0.7)], [_hit("a", 7.0), _hit("x", 3.2)])
    assert {h["text"]: h["score"] for h in hits} == {"a": 0.9, "b": 0.7, "x": 0.33}
    assert [h["text"] for h in hits][0] == "a"  # first in both lists


def test_a_keyword_only_chunk_stored_without_an_id_scores_zero(fused):
    old = {"text": "an old chunk", "meta": {"source": "old.txt"}, "score": 4.0}
    assert [(h["text"], h["score"]) for h in fused([], [old])] == [("an old chunk", 0.0)]


def test_fusion_returns_at_most_k(fused):
    hits = fused([_hit(t) for t in "abcdef"], [_hit(t) for t in "ghij"], k=3)
    assert len(hits) == 3


def test_fusion_does_not_change_the_input_hits(fused):
    dense, bm25 = [_hit("a", score=0.42)], [_hit("a", score=7.0), _hit("x", score=3.2)]
    fused(dense, bm25)
    assert dense[0]["score"] == 0.42 and bm25[1]["score"] == 3.2


@pytest.mark.parametrize("dense,bm25,expected", [
    ([], [], []),
    ([_hit("a", 0.8), _hit("b", 0.7)], [], [("a", 0.8), ("b", 0.7)]),
    ([], [_hit("c", 3.2)], [("c", 0.33)]),
])
def test_fusion_with_one_side_empty_uses_the_same_score_scale(fused, dense, bm25, expected):
    # R3: the fallback branches used to return a different scale from the fused branch
    assert [(h["text"], h["score"]) for h in fused(dense, bm25)] == expected


# ── The LangChain retriever object (Task 14) ──────────────────────────────────

def test_user_retriever_is_a_langchain_retriever_over_the_dense_search(user):
    from langchain_core.retrievers import BaseRetriever
    lc = retriever.UserRetriever(tenant=user, k=2)
    assert isinstance(lc, BaseRetriever)
    docs = lc.invoke("When are impeller seals on centrifugal pumps replaced?")
    dense = retriever.retriever.search(user, "When are impeller seals on centrifugal pumps replaced?", k=2)
    assert [d.page_content for d in docs] == [h["text"] for h in dense]
    assert [d.metadata["score"] for d in docs] == [h["score"] for h in dense]
    assert retriever.UserRetriever(tenant="tenant-870099", k=2).invoke("pumps") == []
