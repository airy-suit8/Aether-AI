"""
retrieval/scope.py — which of a user's documents a question is about.

A question is searched in every one of the user's ready documents, unless
  - the request chooses some (document_ids: the composer's "Search in"), or
  - the question names them: two or more words in a row from a document's title or opening
    lines ("the Classification of Maternal Health paper", "the paper by Hardik Kumar"), two
    words of its file name or the number in it ("Ganatra Recos", "13003"), or a kind of file
    ("the PDF", "the Word file").
The answer says which documents were searched (Scope.described), so a wrong guess is seen and
can be put right with "Search in".

Two kinds of question are flagged for the pipeline, which then reads each document's own
passages rather than only the best few overall (pipeline/rag.py, retrieve):
  each          one about several documents at once ("both papers", "each document");
  front_matter  one about what a document's opening says: its title, authors, ORCID ids,
                affiliations, e-mail addresses or abstract. A paper names its own authors at its
                start; the best matches for "authors" are otherwise its reference list, which
                names the authors of other works.
"""

import re
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Dict, List, Optional

from src.db.database import get_all_documents_detailed, get_tenant_id
from src.vectordb.vector_store import store

# What a file's type (the chunks' "type") is called in a question
KIND_PATTERNS = {
    "pdf": r"\bpdfs?\b",
    "docx": r"\b(?:docx|ms[ -]?word|word (?:files?|documents?|docs?)|the word one)\b",
    "xlsx": r"\b(?:excel|xlsx|spreadsheets?|workbooks?)\b",
    "xls": r"\b(?:excel|xls|spreadsheets?|workbooks?)\b",
    "csv": r"\bcsvs?\b",
    "text": r"\b(?:txt|text files?|markdown)\b",
}
KIND_NAMES = {"pdf": "PDF", "docx": "Word", "xlsx": "Excel", "xls": "Excel", "csv": "CSV", "text": "text"}

EACH = re.compile(r"\b(?:both|each|every|all (?:the |my |of the )?(?:documents|papers|files|articles))\b", re.I)
# A question that refers to a document as one: only then can it name one by its words
NOUNS = r"papers?|documents?|docs?|files?|articles?|letters?|reports?|theses|thesis|manuals?|pdfs?|docx|spreadsheets?"
REFERS = re.compile(rf"\b(?:{NOUNS}|titled|called|named)\b", re.I)
FRONT_MATTER = re.compile(
    r"\b(?:authors?|authored|wrote|written by|writers?|orcids?|affiliations?|affiliated|institutions?|"
    r"e-?mails?|corresponding|titles?|titled|abstract|keywords)\b", re.I)

# Words too common to say which document is meant ("the paper", "this research")
GENERIC = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for", "from", "has", "have", "how",
    "i", "in", "is", "it", "its", "me", "my", "of", "on", "or", "say", "says", "so", "tell", "that", "the",
    "their", "them", "there", "these", "this", "those", "to", "using", "was", "were", "what", "when", "where",
    "which", "who", "whom", "why", "with", "you", "your", "all", "any", "both", "each", "about", "give", "list",
    "show", "find", "document", "documents", "paper", "papers", "file", "files", "article", "articles",
    "report", "reports", "research", "study", "pdf", "docx", "word", "doc", "text", "one", "two", "first",
    "1", "pb", "final", "copy", "format", "column", "version", "draft", "new", "author", "authors",
}
SMALL_WORDS = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "of", "on", "or", "the", "to", "using", "via", "with"}
OPENING_WORDS = 60    # how much of a document's first passage its name may be matched against
MAX_EACH = 6           # the most documents read one by one; more than this are searched together


@dataclass
class Document:
    """One ready document of the user: what a question may call it."""
    id: int
    filename: str
    kind: str        # the chunks' "type": pdf, docx, text, csv, xlsx, xls
    title: str       # the first line of its first passage that reads like a title, or ""
    opening: str     # the start of its first passage, for matching a title or an author

    @property
    def name(self) -> str:
        """How the app shows the document: its title when it has one, else its file name."""
        return self.title or self.filename


@dataclass
class Scope:
    """What a question searches, and why."""
    documents: List[Document]
    how: str                       # "all", "chosen", "named" or "kind"
    each: bool = False
    front_matter: bool = False
    all_documents: List[Document] = field(default_factory=list)

    @property
    def ids(self) -> Optional[List[int]]:
        """The document ids to filter by, or None when every document is searched."""
        return None if self.how == "all" else [d.id for d in self.documents]

    def described(self) -> Dict:
        """For the answer's done event: how the documents were picked, and which they are."""
        return {"how": self.how, "documents": [{"document_id": d.id, "name": d.name, "filename": d.filename}
                                              for d in self.documents]}


class ScopeError(ValueError):
    """The request chose documents, and none of them can be searched."""


def _words(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def title_of(text: str) -> str:
    """The first line of a document's first passage that reads like a title: at least two words
    with letters, not a page number. Lines in capitals that follow one another are one title,
    as a paper's title often runs over two."""
    lines = [" ".join(line.split()) for line in text.splitlines()]
    title: List[str] = []
    for line in lines:
        if len(re.findall(r"[A-Za-z]{2,}", line)) < 2:
            if title:
                break
            continue
        if title and not (line.isupper() and title[-1].isupper()):
            break
        title.append(line)
        if not line.isupper():
            break
    joined = " ".join(title)
    if joined.isupper():  # shown as a title, not shouted; small words stay small after the first
        words = joined.title().split(" ")
        joined = " ".join([words[0]] + [w.lower() if w.lower() in SMALL_WORDS else w for w in words[1:]])
    return joined[:140]


def documents_of(user_id: int) -> List[Document]:
    """The user's ready documents, with what a question may call each."""
    records = [r for r in get_all_documents_detailed(user_id) if r["status"] == "ready"]
    if not records:
        return []
    first = store.first_passages(get_tenant_id(user_id))
    documents = []
    for record in records:
        text, meta = first.get(record["id"], ("", {}))
        kind = meta.get("type") or PurePath(record["filename"]).suffix.lstrip(".").lower()
        documents.append(Document(id=record["id"], filename=record["filename"], kind=kind,
                                  title=title_of(text), opening=" ".join(text.split()[:OPENING_WORDS])))
    return documents


def _longest_shared_run(question: List[str], words: List[str]) -> List[str]:
    """The longest run of words, in order, found in both."""
    best: List[str] = []
    for i in range(len(question)):
        for j in range(len(words)):
            n = 0
            while i + n < len(question) and j + n < len(words) and question[i + n] == words[j + n]:
                n += 1
            if n > len(best):
                best = question[i:i + n]
    return best


def _distinctive(run: List[str]) -> bool:
    """Two or more words with at least one that says something (not "of the", not "the paper")."""
    return len(run) >= 2 and any(w not in GENERIC and len(w) >= 4 for w in run)


def _named(question: str, documents: List[Document]) -> List[Document]:
    """The documents the question calls by their title, opening words or file name: those with the
    longest such run, so "maternal health risks" picks the paper of that title over one that
    merely shares "health". Words in common count only when the question refers to a document
    (REFERS: "the paper", "the Word file", a question about authors or a title): a question about
    the Zephyr turbine is not narrowed to the file that begins with those words."""
    asked = _words(question)
    refers = bool(REFERS.search(question) or FRONT_MATTER.search(question))
    runs = {}
    for doc in documents:
        stem = _words(PurePath(doc.filename).stem)
        run = _longest_shared_run(asked, _words(doc.title) + ["\0"] + _words(doc.opening) + ["\0"] + stem)
        length = len(run) if refers and _distinctive(run) else 0
        # One word of the file name is enough when no other document's name has it, and it is a
        # number ("13003") or stands next to a word for a document ("the Recos file")
        for word in stem:
            if len(word) < 4 or word in GENERIC or word not in asked or \
                    any(word in _words(PurePath(o.filename).stem) for o in documents if o is not doc):
                continue
            beside = re.search(rf"\b{word}\W+(?:{NOUNS})\b|\b(?:{NOUNS})\W+{word}\b", question, re.I)
            if any(c.isdigit() for c in word) or beside:
                length = max(length, 2)
        runs[doc.id] = length
    best = max(runs.values(), default=0)
    return [d for d in documents if best and runs[d.id] == best]


def _of_kind(question: str, documents: List[Document]) -> List[Document]:
    kinds = {kind for kind, pattern in KIND_PATTERNS.items() if re.search(pattern, question, re.I)}
    return [d for d in documents if d.kind in kinds]


def resolve(user_id: int, question: str, chosen: Optional[List[int]] = None, also: str = "") -> Scope:
    """
    The documents a question searches. chosen: the ids the request named (the composer's
    "Search in"); they win over anything the question says. also: more text to look for a
    document's name in, such as the question as rewritten from the conversation.
    """
    documents = documents_of(user_id)
    each = bool(EACH.search(question))
    front_matter = bool(FRONT_MATTER.search(question))
    if chosen is not None:
        picked = [d for d in documents if d.id in set(chosen)]
        if not picked:
            raise ScopeError("None of the documents chosen to search in is in your library and ready.")
        return Scope(picked, "chosen", each, front_matter, documents)
    if len(documents) > 1:
        for text in filter(None, (question, also)):
            named = _named(text, documents)
            if named and len(named) < len(documents):
                return Scope(named, "named", each, front_matter, documents)
            kinds = _of_kind(text, documents)
            if kinds and len(kinds) < len(documents):
                return Scope(kinds, "kind", each, front_matter, documents)
    return Scope(documents, "all", each, front_matter, documents)


def check_chosen(user_id: int, chosen: Optional[List[int]]) -> None:
    """Raise ScopeError before an answer starts when the request chose documents none of which
    can be searched (a stream cannot answer 400 once it has begun)."""
    if chosen is not None:
        ready = {d.id for d in documents_of(user_id)}
        if not ready & set(chosen):
            raise ScopeError("None of the documents chosen to search in is in your library and ready.")
