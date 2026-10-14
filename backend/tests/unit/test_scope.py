"""The parts of retrieval/scope.py that need no library: a document's title, and when a question
refers to a document at all."""

import pytest

from src.retrieval import scope
from src.retrieval.scope import Document


@pytest.mark.parametrize("text,title", [
    ("65 \n \nCLASSIFICATION OF MATERNAL HEALTH RISKS USING \nBOOSTING TECHNIQUE  \n1Caleb Adithia Kurniawan",
     "Classification of Maternal Health Risks using Boosting Technique"),
    ("Automated Post-Disaster Infrastructure Assessment Using Artificial Intelligence\nHardik Kumar Jayswal 1",
     "Automated Post-Disaster Infrastructure Assessment Using Artificial Intelligence"),
    ("Recommendation Letter\nIn my capacity of Head of Department", "Recommendation Letter"),
    ("12\n\n", ""),
    ("", ""),
])
def test_a_title_is_the_first_line_that_reads_like_one(text, title):
    assert scope.title_of(text) == title


def test_a_long_first_line_is_cut():
    assert len(scope.title_of("word " * 100)) == 140


def doc(id, filename, title, opening=""):
    return Document(id=id, filename=filename, kind="pdf", title=title, opening=opening or title)


LIBRARY = [doc(1, "13003-64313-1-PB.pdf", "Classification of Maternal Health Risks"),
           doc(2, "Double-Column-Format.docx", "Automated Post-Disaster Assessment", "Automated Post-Disaster Assessment Hardik Kumar"),
           doc(3, "Tirth Ganatra Recos.docx", "Recommendation Letter")]


@pytest.mark.parametrize("question,ids", [
    ("Authors of Classification of?", [1]),
    ("the paper by Hardik Kumar", [2]),
    ("what does the Recos file say", [3]),
    ("13003: summarise it", [1]),
    ("classification of maternal health risks", []),   # the subject, not a document
    ("the paper on double counting", []),              # a file-name word, but not beside a document word
    ("the paper", []),                                  # nothing distinctive
    ("who are the authors of the paper on post-disaster assessment", [2]),
])
def test_when_a_question_names_a_document(question, ids):
    assert [d.id for d in scope._named(question, LIBRARY)] == ids


def test_two_documents_named_equally_are_both_searched():
    twins = [doc(1, "a.pdf", "Deep Learning Survey"), doc(2, "b.pdf", "Deep Learning Survey Part Two")]
    assert [d.id for d in scope._named("who wrote the deep learning survey paper", twins)] == [1, 2]


@pytest.mark.parametrize("question,each,front", [
    ("Who are the authors of both papers?", True, True),
    ("What does each document conclude?", True, False),
    ("List all the documents' titles", True, True),
    ("What is the ORCID id of the first author?", False, True),
    ("How accurate is the model?", False, False),
])
def test_questions_about_several_documents_or_their_front_matter_are_flagged(question, each, front):
    assert bool(scope.EACH.search(question)) is each
    assert bool(scope.FRONT_MATTER.search(question)) is front


def test_a_scope_of_every_document_filters_by_nothing():
    everything = scope.Scope(LIBRARY, "all")
    assert everything.ids is None
    assert scope.Scope(LIBRARY[:1], "named").ids == [1]
    assert scope.Scope(LIBRARY[:1], "named").described()["documents"] == [
        {"document_id": 1, "name": "Classification of Maternal Health Risks", "filename": "13003-64313-1-PB.pdf"}]
