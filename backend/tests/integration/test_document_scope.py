"""
Which documents a question searches (retrieval/scope.py), through the API, in a library like the
owner's: a PDF paper whose file name says nothing of it, a Word paper with ORCID ids, and a letter.

  - "Search in" (document_ids) limits the search to the documents chosen; none of them ready: 400.
  - A question that refers to a document by its title's first words, a word of its file name next
    to "file" or "letter", or its kind ("the PDF") searches that document only; a question about
    the subject matter that shares words with a title is not narrowed.
  - A question about authors or ORCID ids reads each document's first passage, marked as the
    start; one about "each" or "both" documents reads each one's best passages.
  - The passages either side of the best hits come with them, and every passage is given in
    reading order, with its document's title and its place in it.
  - Every answer says what it searched, and every source where it sits.
The models are the fakes; the prompt the fake received shows what the model was given.
"""

import pytest

from filemakers import make_docx, make_pdf
from helpers import ask, ask_stream
from src.core.config import settings

PDF_PAGES = [
    "65\n\nCLASSIFICATION OF MATERNAL HEALTH RISKS USING\nBOOSTING TECHNIQUE\n"
    "1Caleb Adithia Kurniawan, 2Rosita Herawati\nAbstract: maternal health risk is classified with boosting.",
    "The boosting classifier reached an accuracy of 97 percent on the maternal health data.",
    "REFERENCES\n[1] John Smith and Anna Jones. Deep learning for pregnancy risk. 2020.\n"
    "[2] Kevin Brown. Boosting methods for tabular data. 2019.",
]
PAPER = [
    "Automated Post-Disaster Infrastructure Assessment Using Artificial Intelligence and Satellite Images",
    "Hardik Kumar Jayswal [0000-0002-2224-5258], Nishant Koshti [0009-0001-8101-0846]",
    "Satellite images of damaged roads are classified with a convolutional network.",
]
LETTER = ["Recommendation Letter", "I am happy to recommend Mr. Tirth Ganatra for his work in advanced computing."]
PDF_TITLE = "Classification of Maternal Health Risks using Boosting Technique"


def _upload(client, headers, path, mime):
    r = client.post("/api/v1/upload", headers=headers, files={"file": (path.name, path.read_bytes(), mime)})
    assert r.status_code == 202, r.text
    return r.json()["document_id"]


@pytest.fixture
def library(client, make_user, tmp_path, monkeypatch):
    """A user with the three documents; returns (headers, {"pdf": id, "paper": id, "letter": id}).
    The fake embeddings score these short questions low; the refusal threshold is not what these
    tests are about, so nothing is refused for it."""
    monkeypatch.setattr(settings, "confidence_threshold", 0.0)
    _, headers = make_user("scope")
    word = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ids = {
        "pdf": _upload(client, headers, make_pdf(tmp_path / "13003-64313-1-PB.pdf", PDF_PAGES), "application/pdf"),
        "paper": _upload(client, headers, make_docx(tmp_path / "Double-Column-Format-1-1 (1).docx", PAPER), word),
        "letter": _upload(client, headers, make_docx(tmp_path / "Tirth Ganatra Recos.docx", LETTER), word),
    }
    return headers, ids


def _searched(body):
    return body["scope"]["how"], sorted(d["document_id"] for d in body["scope"]["documents"])


def _prompt(fake_llm):
    return fake_llm.prompts[-1]


# ── What the library calls each document ──────────────────────────────────────

def test_the_library_lists_each_document_s_title_and_kind(client, library):
    headers, ids = library
    docs = {d["id"]: d for d in client.get("/api/v1/documents/detailed", headers=headers).json()["documents"]}
    assert (docs[ids["pdf"]]["title"], docs[ids["pdf"]]["kind"]) == (PDF_TITLE, "pdf")
    assert docs[ids["paper"]]["title"] == PAPER[0] and docs[ids["paper"]]["kind"] == "docx"
    assert docs[ids["letter"]]["title"] == "Recommendation Letter"


# ── Search in: the documents chosen ───────────────────────────────────────────

def test_search_in_limits_the_answer_to_the_documents_chosen(client, library, fake_llm):
    headers, ids = library
    body = ask(client, headers, "What is classified?", document_ids=[ids["paper"]]).json()
    assert _searched(body) == ("chosen", [ids["paper"]])
    assert {s["document_id"] for s in body["sources"]} == {ids["paper"]}
    assert "maternal" not in _prompt(fake_llm).lower()

    status, events = ask_stream(client, headers, "What is classified?", document_ids=[ids["pdf"], ids["letter"]])
    assert status == 200 and _searched(events[-1]) == ("chosen", sorted([ids["pdf"], ids["letter"]]))


def test_choosing_only_documents_that_are_not_yours_is_refused(client, library, make_user):
    headers, ids = library
    _, stranger = make_user("stranger")
    for route in ("/api/v1/chat", "/api/v1/chat/stream"):
        r = client.post(route, headers=stranger, json={"question": "Who wrote it?", "document_ids": [ids["pdf"]]})
        assert r.status_code == 400 and "None of the documents chosen" in r.json()["detail"]
    r = client.post("/api/v1/chat", headers=headers, json={"question": "Who wrote it?", "document_ids": []})
    assert r.status_code == 422


# ── Named in the question ─────────────────────────────────────────────────────

def test_a_paper_named_by_its_title_s_first_words_is_the_only_one_searched(client, library, fake_llm):
    headers, ids = library
    body = ask(client, headers, "Classification of: who were the authors and what are their ORCID ids?").json()
    assert _searched(body) == ("named", [ids["pdf"]])
    prompt = _prompt(fake_llm)
    # Its first passage is there, marked as the start, where the paper names its own authors
    assert "Caleb Adithia Kurniawan" in prompt and 'part="start"' in prompt
    assert f'title="{PDF_TITLE}"' in prompt
    assert "Hardik Kumar Jayswal" not in prompt  # the Word paper was not searched


@pytest.mark.parametrize("question,named", [
    ("Who wrote the paper by Hardik Kumar?", "paper"),
    ("What does the Recos letter say?", "letter"),
    ("Summarise the 13003 document.", "pdf"),
])
def test_a_document_is_named_by_its_authors_or_its_file_name(client, library, question, named):
    headers, ids = library
    assert _searched(ask(client, headers, question).json()) == ("named", [ids[named]])


@pytest.mark.parametrize("question,kind", [("What accuracy does the PDF report?", ["pdf"]),
                                           ("What do the Word files say?", ["paper", "letter"])])
def test_a_kind_of_file_named_in_the_question_is_searched(client, library, question, kind):
    headers, ids = library
    assert _searched(ask(client, headers, question).json()) == ("kind", sorted(ids[k] for k in kind))


@pytest.mark.parametrize("question", [
    "How accurate is the boosting classifier on maternal health data?",  # words of the PDF's title
    "What does the paper say about double counting?",                    # "Double" is in a file name
])
def test_a_question_about_the_subject_is_not_narrowed_by_shared_words(client, library, question):
    headers, ids = library
    assert _searched(ask(client, headers, question).json()) == ("all", sorted(ids.values()))


# ── Front matter, and each document ───────────────────────────────────────────

def test_a_question_about_the_authors_reads_every_document_s_first_passage(client, library, fake_llm, monkeypatch):
    headers, _ = library
    monkeypatch.setattr(settings, "top_k", 1)  # the search alone would find one passage
    ask(client, headers, "Who are the authors?")
    prompt = _prompt(fake_llm)
    for opening in ("Caleb Adithia Kurniawan", "Hardik Kumar Jayswal", "Recommendation Letter"):
        assert opening in prompt
    assert prompt.count('part="start">') == 3  # one tag each (the rules mention the mark too)


def test_both_papers_get_their_own_best_passages(client, library, fake_llm, monkeypatch):
    headers, ids = library
    monkeypatch.setattr(settings, "top_k", 2)
    monkeypatch.setattr(settings, "chunk_window", 0)
    body = ask(client, headers, "What does each paper classify?", document_ids=[ids["pdf"], ids["paper"]]).json()
    assert {s["document_id"] for s in body["sources"]} <= {ids["pdf"], ids["paper"]}
    prompt = _prompt(fake_llm)
    assert "Satellite images" in prompt and "boosting" in prompt.lower()


# ── Context around a passage, in reading order ────────────────────────────────

def test_the_passages_either_side_of_the_best_hit_come_with_it_in_page_order(client, library, fake_llm, monkeypatch):
    headers, ids = library
    monkeypatch.setattr(settings, "top_k", 1)
    question = "What accuracy did the boosting classifier reach on the maternal health data?"
    ask(client, headers, question, document_ids=[ids["pdf"]])
    prompt = _prompt(fake_llm)
    pages = [prompt.find(text) for text in ("CLASSIFICATION OF", "accuracy of 97 percent", "REFERENCES")]
    assert -1 not in pages and pages == sorted(pages)
    assert 'passage="2 of 3"' in prompt

    monkeypatch.setattr(settings, "chunk_window", 0)
    ask(client, headers, question, document_ids=[ids["pdf"]])
    assert "REFERENCES" not in _prompt(fake_llm) and "accuracy of 97 percent" in _prompt(fake_llm)


def test_a_source_says_which_document_it_is_and_where_it_sits(client, library):
    headers, ids = library
    body = ask(client, headers, "What is in the 13003 document?").json()
    source = body["sources"][0]
    assert (source["document_id"], source["kind"]) == (ids["pdf"], "pdf")
    assert 1 <= source["passage"] <= source["passages"] == 3


def test_a_refusal_still_says_what_was_searched(client, library, monkeypatch):
    headers, ids = library
    monkeypatch.setattr(settings, "confidence_threshold", 1.1)
    body = ask(client, headers, "Anything?", document_ids=[ids["letter"]]).json()
    assert body["sources"] == [] and _searched(body) == ("chosen", [ids["letter"]])


def test_the_agent_searches_only_the_documents_chosen(client, library):
    headers, ids = library
    body = ask(client, headers, "What is classified?", mode="agent", document_ids=[ids["paper"]]).json()
    assert _searched(body) == ("chosen", [ids["paper"]])
    assert body["sources"] and {s["source"] for s in body["sources"]} == {"Double-Column-Format-1-1 (1).docx"}
