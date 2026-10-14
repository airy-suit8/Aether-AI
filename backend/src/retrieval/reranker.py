"""
retrieval/reranker.py — put a search's passages in order again, by how well each answers the question.

A search compares the meaning of the question with each passage's, one at a time; a cross-encoder
reads the question and a passage together and scores how well the passage answers it. On the
owner's papers this brought the passage with a paper's own result into the five the model reads,
where the search alone had ranked a cited study's result above it (SPRINT_PLAN.md, "Reranking").

The model is settings.rerank_model, run on the processor by fastembed (ONNX; no PyTorch, no GPU).
It is loaded once: at startup (warm(), in the background) or by the first question. When it cannot
be loaded (no network the first time it is downloaded, say), questions are answered in the search's
own order and the log says why, once.
"""

import logging
import threading
from typing import Any, Dict, List, Optional

from src.core.config import settings
from src.core.logging import error_logger, log_event

_lock = threading.Lock()
_loaded: Optional[tuple] = None   # (model id, cross-encoder)
_failed: Optional[str] = None     # a model id that could not be loaded


def enabled() -> bool:
    """Whether searches are reranked: a model is set, and it has not failed to load."""
    return bool(settings.rerank_model) and _failed != settings.rerank_model


def _load(model: str):
    """The cross-encoder. fastembed is imported here: importing it takes seconds."""
    from fastembed.rerank.cross_encoder import TextCrossEncoder
    return TextCrossEncoder(model_name=model, cache_dir=str(settings.model_dir))


def _encoder():
    """The loaded cross-encoder for settings.rerank_model, or None when it cannot be loaded."""
    global _loaded, _failed
    model = settings.rerank_model
    with _lock:  # a second question waits for the first to finish loading it
        if _loaded is None or _loaded[0] != model:
            try:
                _loaded = (model, _load(model))
            except Exception as e:
                _failed = model
                log_event(error_logger, "rerank_model_unavailable", level=logging.WARNING, model=model, cause=repr(e))
                return None
        return _loaded[1]


def warm() -> None:
    """Load the model now, so the first question does not wait for it (run at startup)."""
    if enabled():
        _encoder()


def rerank(query: str, hits: List[Dict[str, Any]], k: int) -> List[Dict[str, Any]]:
    """
    The k hits that answer the query best, best first, each with "relevance": the model's score
    (higher is better; not a probability). Without a model, the first k in the search's order.
    """
    encoder = _encoder() if enabled() and len(hits) > 1 else None
    if encoder is None:
        return hits[:k]
    try:
        scores = [float(s) for s in encoder.rerank(query, [h["text"] for h in hits])]
    except Exception as e:  # the search's order is still an answer
        log_event(error_logger, "rerank_failed", level=logging.WARNING, model=settings.rerank_model, cause=repr(e))
        return hits[:k]
    best = sorted(range(len(hits)), key=lambda i: -scores[i])[:k]
    return [{**hits[i], "relevance": round(scores[i], 3)} for i in best]
