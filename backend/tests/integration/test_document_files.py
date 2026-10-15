"""
A source shown in its place (the page viewer): a PDF is kept as it was uploaded, and a passage can
be read with the ones either side of it.

  - GET /documents/{id}/file gives the PDF as uploaded; only its owner gets it; a Word file is
    not kept; the file goes with its document (removed, replaced, the library cleared), and a
    PDF that could not be read is not kept.
  - A PDF uploaded before files were kept, uploaded again, is kept for its document without
    being read twice; a third upload is the usual duplicate.
  - GET /documents/{id}/passages/{n} gives passage n and `around` either side, in order, with
    the document's kind, its number of passages and whether its PDF is kept.
"""

import pytest

from filemakers import make_docx, make_pdf
from helpers import status_of, tenant_of
from src.core.config import settings

PAGES = [f"Page {i} of the boiler manual: the burner is checked every {i * 10} days." for i in range(1, 6)]
WORD = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _upload(client, headers, path, mime="application/pdf"):
    return client.post("/api/v1/upload", headers=headers, files={"file": (path.name, path.read_bytes(), mime)})


@pytest.fixture
def owner(client, make_user, tmp_path):
    """A user with a five-page PDF; returns (headers, document id, the PDF's bytes)."""
    _, headers = make_user("pages")
    pdf = make_pdf(tmp_path / "boiler manual.pdf", PAGES)
    record = status_of(client, headers, _upload(client, headers, pdf))
    assert record["status"] == "ready", record
    return headers, record["id"], pdf.read_bytes()


def _file(client, headers, document_id):
    return client.get(f"/api/v1/documents/{document_id}/file", headers=headers)


def _kept(headers, document_id):
    return settings.files_dir / tenant_of(headers) / f"{document_id}.pdf"


# ── The file ──────────────────────────────────────────────────────────────────

def test_a_pdf_is_kept_as_it_was_uploaded(client, owner):
    headers, document_id, pdf = owner
    r = _file(client, headers, document_id)
    assert r.status_code == 200
    assert r.content == pdf
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].startswith("inline")
    assert _kept(headers, document_id).is_file()


def test_only_its_owner_gets_the_file_or_its_passages(client, owner, make_user):
    _, document_id, _ = owner
    _, other = make_user("other")
    assert _file(client, other, document_id).status_code == 404
    assert client.get(f"/api/v1/documents/{document_id}/passages/1", headers=other).status_code == 404
    assert client.get(f"/api/v1/documents/{document_id}/file").status_code == 401


def test_a_word_file_is_not_kept_and_says_why(client, make_user, tmp_path):
    _, headers = make_user("word")
    docx = make_docx(tmp_path / "letter.docx", ["Dear reader,", "The burner is checked monthly."])
    record = status_of(client, headers, _upload(client, headers, docx, WORD))
    r = _file(client, headers, record["id"])
    assert r.status_code == 404 and "Upload the same PDF again" in r.json()["detail"]
    passages = client.get(f"/api/v1/documents/{record['id']}/passages/1", headers=headers).json()
    assert passages["kind"] == "docx" and passages["original"] is False


def test_the_file_goes_with_its_document(client, owner):
    headers, document_id, _ = owner
    assert client.delete(f"/api/v1/documents/{document_id}", headers=headers).status_code == 200
    assert not _kept(headers, document_id).exists()
    assert _file(client, headers, document_id).status_code == 404


def test_clearing_the_library_removes_every_file(client, owner):
    headers, document_id, _ = owner
    assert client.delete("/api/v1/documents", headers=headers).status_code == 200
    assert not (settings.files_dir / tenant_of(headers)).exists()


def test_a_replaced_pdf_takes_its_file_with_it(client, owner, tmp_path):
    headers, old_id, _ = owner
    changed = make_pdf(tmp_path / "boiler manual.pdf", PAGES + ["A new page six."])
    new = status_of(client, headers, _upload(client, headers, changed))
    assert new["status"] == "ready" and new["id"] != old_id
    assert not _kept(headers, old_id).exists()
    assert _file(client, headers, new["id"]).content == changed.read_bytes()


def test_a_pdf_that_cannot_be_read_is_not_kept(client, make_user, tmp_path):
    _, headers = make_user("scan")
    record = status_of(client, headers, _upload(client, headers, make_pdf(tmp_path / "scan.pdf", ["", ""])))
    assert record["status"] == "failed"
    assert not _kept(headers, record["id"]).exists()


def test_a_pdf_from_before_files_were_kept_is_kept_when_uploaded_again(client, owner, tmp_path):
    headers, document_id, pdf = owner
    _kept(headers, document_id).unlink()  # as uploaded before 15 Oct 2026
    chunks = status_of(client, headers, client.post("/api/v1/upload", headers=headers, files={
        "file": ("boiler manual.pdf", pdf, "application/pdf")}))
    again = client.post("/api/v1/upload", headers=headers, files={"file": ("a copy.pdf", pdf, "application/pdf")})
    assert again.status_code == 409  # now it is kept, the same file is the usual duplicate
    assert chunks["id"] == document_id and chunks["chunks"] == len(PAGES)  # not read twice
    assert _file(client, headers, document_id).content == pdf
    library = client.get("/api/v1/documents/detailed", headers=headers).json()
    assert library["count"] == 1


def test_uploading_it_again_says_the_file_was_kept(client, owner):
    headers, document_id, pdf = owner
    _kept(headers, document_id).unlink()
    r = client.post("/api/v1/upload", headers=headers, files={"file": ("boiler manual.pdf", pdf, "application/pdf")})
    assert r.status_code == 202
    assert r.json() == {"document_id": document_id, "filename": "boiler manual.pdf", "status": "ready", "replaces": False,
                        "message": "Kept the file of 'boiler manual.pdf', to show its pages."}


# ── Passages in their place ───────────────────────────────────────────────────

def test_a_passage_comes_with_the_ones_either_side(client, owner):
    headers, document_id, _ = owner
    r = client.get(f"/api/v1/documents/{document_id}/passages/3", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["document_id"] == document_id and body["filename"] == "boiler manual.pdf"
    assert body["kind"] == "pdf" and body["passages"] == 5 and body["original"] is True
    assert [(p["passage"], p["page"]) for p in body["items"]] == [(2, 2), (3, 3), (4, 4)]
    assert "every 30 days" in body["items"][1]["text"]


def test_the_first_and_last_passages_and_how_many_around(client, owner):
    headers, document_id, _ = owner
    first = client.get(f"/api/v1/documents/{document_id}/passages/1?around=2", headers=headers).json()
    assert [p["passage"] for p in first["items"]] == [1, 2, 3]
    alone = client.get(f"/api/v1/documents/{document_id}/passages/5?around=0", headers=headers).json()
    assert [p["passage"] for p in alone["items"]] == [5]


@pytest.mark.parametrize("path, status", [("passages/6", 404), ("passages/0", 422), ("passages/2?around=4", 422)])
def test_a_passage_it_does_not_have(client, owner, path, status):
    headers, document_id, _ = owner
    assert client.get(f"/api/v1/documents/{document_id}/{path}", headers=headers).status_code == status
