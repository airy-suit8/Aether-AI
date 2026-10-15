"""
PDF pages that are pictures of text (scans, photos) are read by OCR (ingestion/ocr.py), with a fake
OCR engine in place of RapidOCR. The pages themselves are really drawn, by pdfium.

  - only the pages with no text are drawn and read, and each is marked as read by OCR;
  - OCR turned off, too many such pages, an engine that fails, or a page it finds nothing on: the
    upload is refused with a message that says which;
  - through the API, a scanned PDF is read and its passages can be asked about.
"""

import pytest

from fakes import FakeOcr
from filemakers import make_pdf
from helpers import ask, status_of
from src.core.config import settings
from src.ingestion import ocr
from src.ingestion.loader import DocumentError, load_document_native


@pytest.fixture
def engine(monkeypatch):
    """OCR on, with a fake engine; set its .pages to the lines it should find on each picture."""
    fake = FakeOcr()
    monkeypatch.setattr(settings, "ocr", True)
    monkeypatch.setattr(ocr, "_engine", fake)
    return fake


def test_pages_that_are_pictures_are_read_by_ocr_and_marked(engine, tmp_path):
    engine.pages = [["Results For Splitting 80:20", "XGBoost has the highest accuracy of 83.7%."], []]
    docs = load_document_native(str(make_pdf(tmp_path / "paper.pdf", ["The abstract, as text.", "", ""])), "paper.pdf")
    assert [(d.metadata["page"], d.metadata.get("ocr")) for d in docs] == [(1, None), (2, True)]
    assert docs[1].page_content == "Results For Splitting 80:20\nXGBoost has the highest accuracy of 83.7%."
    # Only the two pages without text were drawn, at 200 dpi (a 612 x 792 pt page is 1700 x 2200 px)
    assert engine.pictures == [(2200, 1700, 3), (2200, 1700, 3)]


def test_a_pdf_with_text_on_every_page_is_not_drawn(engine, tmp_path):
    load_document_native(str(make_pdf(tmp_path / "text.pdf", ["One.", "Two."])), "text.pdf")
    assert engine.pictures == []


def test_a_scan_ocr_finds_nothing_on_says_so(engine, tmp_path):
    with pytest.raises(DocumentError, match="look like scans or photos, and OCR found no words on them either"):
        load_document_native(str(make_pdf(tmp_path / "blank.pdf", ["", ""])), "blank.pdf")


def test_with_ocr_turned_off_a_scan_is_refused_as_before(engine, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ocr", False)
    with pytest.raises(DocumentError, match="OCR\\) is turned off on this server"):
        load_document_native(str(make_pdf(tmp_path / "scan.pdf", [""])), "scan.pdf")
    assert engine.pictures == []


def test_a_file_with_too_many_pictures_is_refused_before_any_is_read(engine, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ocr_max_pages", 2)
    with pytest.raises(DocumentError, match="has 3 pages that are pictures of text, and at most 2"):
        load_document_native(str(make_pdf(tmp_path / "long.pdf", ["", "", ""])), "long.pdf")
    assert engine.pictures == []


def test_an_engine_that_fails_is_a_refusal_with_its_cause_kept(monkeypatch, tmp_path):
    def broken(picture):
        raise RuntimeError("onnxruntime: bad model")

    monkeypatch.setattr(settings, "ocr", True)
    monkeypatch.setattr(ocr, "_engine", broken)
    with pytest.raises(DocumentError, match="OCR could not read them on this server") as refused:
        load_document_native(str(make_pdf(tmp_path / "scan.pdf", [""])), "scan.pdf")
    assert "bad model" in repr(refused.value.__cause__)


def test_the_engine_is_loaded_once(monkeypatch, tmp_path):
    loads = []
    monkeypatch.setattr(settings, "ocr", True)
    monkeypatch.setattr(ocr, "_engine", None)
    monkeypatch.setattr(ocr, "_load", lambda: loads.append(1) or FakeOcr([["Some words here."]] * 2))
    for name in ("a.pdf", "b.pdf"):
        load_document_native(str(make_pdf(tmp_path / name, [""])), name)
    assert loads == [1]


def test_a_scanned_pdf_upload_is_read_and_can_be_asked_about(client, make_user, tmp_path, engine, monkeypatch):
    monkeypatch.setattr(settings, "confidence_threshold", 0.0)
    engine.pages = [["The burner is inspected every 90 days by a registered engineer."]]
    _, headers = make_user("ocr")
    pdf = make_pdf(tmp_path / "scanned manual.pdf", [""])
    r = client.post("/api/v1/upload", headers=headers, files={"file": (pdf.name, pdf.read_bytes(), "application/pdf")})
    document = status_of(client, headers, r)
    assert document["status"] == "ready" and document["chunks"] == 1
    answer = ask(client, headers, "How often is the burner inspected?").json()
    assert answer["sources"] and answer["sources"][0]["source"] == "scanned manual.pdf"
    passage = client.get(f"/api/v1/documents/{document['id']}/passages/1", headers=headers).json()
    assert "every 90 days" in passage["items"][0]["text"]
