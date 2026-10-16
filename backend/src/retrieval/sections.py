"""
retrieval/sections.py — the section of its paper each passage is in ("Introduction", "Results"),
for its <document> tag (D-074).

A figure in a paper's introduction or literature review is usually another study's result; the
paper's own are in its results, discussion and conclusion. Asked for a paper's best accuracy, a
small model gave a cited study's 97.03% from the literature review, which cites no work in that
passage. With the section in the tag, the prompt can say which figures are the paper's own.

A section starts at a line that is only a usual section name (Abstract, Introduction, Related
work, Literature review, Methodology, Results, Discussion, Conclusion, References and their
like), numbered or not, in capitals or not. Other headings ("Data Visualization", "XGBoost
Classifier") are too varied to tell from a short sentence, so they start none. A passage that
crosses a heading is in both ("Introduction, then Literature study"); a document with no such
heading (a letter) has no sections.

They are found from the stored passages of each document asked about, in order, and kept until
the tenant's passages change (store.version).
"""

import re
import threading
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

from src.vectordb.vector_store import store

SECTION_NAMES = frozenset({
    "abstract", "introduction", "background", "related work", "related works", "literature review",
    "literature study", "literature survey", "review of literature", "method", "methods", "methodology",
    "research methodology", "materials and methods", "proposed method", "proposed methodology",
    "dataset", "datasets", "experiment", "experiments", "experimental setup", "experimental results",
    "implementation", "implementation and results", "evaluation", "results", "results and discussion",
    "discussion", "conclusion", "conclusions", "conclusion and future work", "future work",
    "acknowledgement", "acknowledgements", "acknowledgment", "acknowledgments", "references", "bibliography",
})

# "3.", "4.1", "II.", "A." before the name; "(ABSTRACT TITLE)" or ":" after it
_HEADING = re.compile(r"^(?:\d+(?:\.\d+)*\.?|[IVX]+\.|[A-Z]\.)?\s*(?P<name>[A-Za-z][A-Za-z &-]*?)\s*(?:\([^)]*\))?\s*:?$")

DOCUMENTS_KEPT = 256  # documents whose sections are kept, most recently asked about

_kept: "OrderedDict[Tuple[str, Any], Tuple[int, Dict[int, str]]]" = OrderedDict()
_kept_lock = threading.Lock()


def heading(line: str) -> Optional[str]:
    """The section a line starts, as it is written there ("Literature study"), or None."""
    found = _HEADING.match(line.strip())
    if not found:
        return None
    name = " ".join(found.group("name").replace("&", " and ").split())
    return name.capitalize() if name.lower() in SECTION_NAMES else None


def sections_of(passages: List[str]) -> List[str]:
    """The section of each of a document's passages, given in order: the one its text starts in,
    then each one it crosses into, joined ("Introduction, then Literature study"); "" before the
    first. A passage that opens with a heading is only in the section that heading starts."""
    current, named = "", []
    for text in passages:
        parts: List[str] = []
        for line in text.split("\n"):
            started = heading(line)
            if started:
                if not parts or parts[-1] != started:
                    parts.append(started)
            elif line.strip() and not parts and current:
                parts.append(current)
        if not parts and current:
            parts.append(current)
        current = parts[-1] if parts else current
        named.append(", then ".join(parts))
    return named


def _document_sections(tenant: str, document_id: Any) -> Dict[int, str]:
    """A document's sections by passage number, from its stored passages; kept until they change."""
    key, version = (tenant, document_id), store.version(tenant)
    with _kept_lock:
        kept = _kept.get(key)
        if kept and kept[0] == version:
            _kept.move_to_end(key)
            return kept[1]
    passages = store.passages_of(tenant, document_id)
    named = sections_of([text for text, _ in passages])
    found = {meta["chunk_index"]: section for (_, meta), section in zip(passages, named) if section}
    with _kept_lock:
        _kept[key] = (version, found)
        _kept.move_to_end(key)
        while len(_kept) > DOCUMENTS_KEPT:
            _kept.popitem(last=False)
    return found


def name_sections(tenant: str, hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The hits, each given its "section" in its meta when its document has one there. The meta
    is copied, not changed: a search may hand out the same dictionaries again."""
    named = []
    for hit in hits:
        meta = hit["meta"]
        document_id, number = meta.get("document_id"), meta.get("chunk_index")
        section = _document_sections(tenant, document_id).get(number) if document_id is not None and number else None
        named.append({**hit, "meta": {**meta, "section": section}} if section else hit)
    return named
