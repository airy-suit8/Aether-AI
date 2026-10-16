"""
The section of its paper each passage is in (retrieval/sections.py, D-074), found from the
headings in the passages themselves, and named in its <document> tag.

  - a line that is only a usual section name starts a section, numbered or not, in capitals or
    not; other headings and sentences do not;
  - a passage that crosses a heading is in both; one that opens with a heading only in its own;
  - through the API, the cited study's figure is tagged as the literature study's and the paper's
    own as its results'; a document without such headings has no section;
  - a document's sections are found once, and again only when the tenant's passages change.
"""

import pytest

from filemakers import make_pdf
from helpers import ask, tenant_of, upload_text
from src.core.config import settings
from src.retrieval import sections
from src.vectordb.vector_store import store


@pytest.mark.parametrize("line, section", [
    # The owner's two papers' headings, as their passages hold them
    ("INTRODUCTION", "Introduction"),
    ("ABSTRACT (ABSTRACT TITLE)", "Abstract"),
    ("LITERATURE STUDY", "Literature study"),
    ("IMPLEMENTATION AND RESULTS", "Implementation and results"),
    ("2.\tRelated Work", "Related work"),
    ("3. DATASET", "Dataset"),
    ("5. experiments", "Experiments"),
    ("6. Conclusions", "Conclusions"),
    ("  Discussion  ", "Discussion"),
    ("I. INTRODUCTION", "Introduction"),
    ("Results & Discussion", "Results and discussion"),
    ("Conclusion:", "Conclusion"),
    # Not sections: other headings, and sentences
    ("Data Visualization", None),
    ("XGBoost Classifier", None),
    ("Test Results", None),
    ("4.1 Pre-processing", None),
    ("Keywords: classification, boosting, machine learning", None),
    ("The results are shown in Table 2.", None),
    ("", None),
])
def test_a_line_that_is_only_a_section_name_starts_that_section(line, section):
    assert sections.heading(line) == section


def test_each_passage_is_in_the_section_its_text_is_in():
    passages = [
        "CLASSIFICATION OF MATERNAL HEALTH RISKS\nCaleb Adithia Kurniawan",  # before any heading
        "ABSTRACT (ABSTRACT TITLE)\nMaternal health is an important concern.",
        "it is classified by age.\nINTRODUCTION\nA hybrid model reached 94.9% [5].",
        "66\n\nthe 15 algorithms [5].\nLITERATURE STUDY\nTogunwa et al. [5] studied",
        "97.03% and a training accuracy of 99.40%.",
        "LITERATURE STUDY\nthe overlap repeats the heading",                  # the overlap of two passages
        "RESEARCH METHODOLOGY\nData Visualization\nThe dataset was split.",
        "Results\nXGBoost has the highest accuracy of 83.7%.\nDiscussion\nXGBoost suits the data.",
        "",
    ]
    assert sections.sections_of(passages) == [
        "",
        "Abstract",
        "Abstract, then Introduction",
        "Introduction, then Literature study",
        "Literature study",
        "Literature study",
        "Research methodology",
        "Results, then Discussion",
        "Discussion",
    ]


def test_a_document_with_no_section_headings_has_none():
    assert sections.sections_of(["Dear Sir,\nI recommend Tirth.", "Name: Dr. Parth Goel\nSignature:"]) == ["", ""]


# ── Through the API ───────────────────────────────────────────────────────────

PAGES = [
    "Classification of maternal health risks using boosting\nABSTRACT\nBoosting classifies the risk.",
    "INTRODUCTION\nA hybrid model reached the highest accuracy of 94.9% [5].",
    "LITERATURE STUDY\nA boosted random forest reached a testing accuracy of 97.03%.",
    "RESULTS\nOur XGBoost classifier reached the highest accuracy of 83.7%.",
    "CONCLUSION\nBoosting can classify maternal health risks.",
]


@pytest.fixture
def every_passage(monkeypatch):
    """Every passage of a small document reaches the model, none refused for the fake scores."""
    monkeypatch.setattr(settings, "top_k", 8)
    monkeypatch.setattr(settings, "rerank_model", "")
    monkeypatch.setattr(settings, "confidence_threshold", 0.0)


def _tag_of(prompt: str, text: str) -> str:
    """The <document ...> line of the passage holding text."""
    before = prompt[:prompt.index(text)]
    return before[before.rindex("<document "):].split("\n")[0]


def test_the_cited_figure_is_tagged_as_the_literature_s_and_the_paper_s_own_as_its_results(
        client, make_user, tmp_path, fake_llm, every_passage):
    _, headers = make_user("sections")
    pdf = make_pdf(tmp_path / "paper.pdf", PAGES)
    assert client.post("/api/v1/upload", headers=headers,
                       files={"file": (pdf.name, pdf.read_bytes(), "application/pdf")}).status_code == 202
    assert ask(client, headers, "What is the best accuracy in the paper?").status_code == 200
    prompt = fake_llm.prompts[-1]
    assert 'section="Literature study"' in _tag_of(prompt, "97.03%")
    assert 'section="Introduction"' in _tag_of(prompt, "94.9%")
    assert 'section="Results"' in _tag_of(prompt, "83.7%")
    assert 'section="Abstract"' in _tag_of(prompt, "Boosting classifies the risk.")
    # And the rule that says what the section means is in the prompt
    assert "figures in an introduction, background, related work or literature review are other studies' results" in prompt


def test_a_document_without_section_headings_gets_no_section(client, make_user, fake_llm, every_passage):
    _, headers = make_user("nosections")
    assert upload_text(client, headers).status_code == 202
    assert ask(client, headers, "How often are the blades inspected?").status_code == 200
    assert "section=" not in fake_llm.prompts[-1]


def test_a_document_s_sections_are_found_once_until_its_passages_change(client, make_user, monkeypatch):
    _, headers = make_user("sectioncache")
    tenant = tenant_of(headers)
    hit = {"text": "x", "meta": {"document_id": 1, "chunk_index": 2}, "score": 0.5}
    reads = []

    def passages_of(t, document_id):
        reads.append(document_id)
        return [("INTRODUCTION\nWhy.", {"chunk_index": 1}), ("Results\nWhat.", {"chunk_index": 2})]

    monkeypatch.setattr(sections, "_kept", type(sections._kept)())
    monkeypatch.setattr(store, "passages_of", passages_of)
    named = sections.name_sections(tenant, [hit])
    assert named[0]["meta"]["section"] == "Results"
    assert "section" not in hit["meta"]  # the search's own dictionary is not changed
    sections.name_sections(tenant, [hit])
    assert reads == [1]
    store._changed(tenant)  # an upload or a deletion
    sections.name_sections(tenant, [hit])
    assert reads == [1, 1]
