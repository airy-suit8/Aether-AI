"""
Upload limits (S4, Sprint 5 item 4): the token is checked before the body is read; the body is
streamed to disk and refused once it passes the size limit; a zip-based file is refused when it
would unpack to too much; tables and documents have row and passage caps; each user has a quota.

The size tests call the app directly over ASGI with a body that is made as it is read, because
the test client reads a whole request body into memory before the app sees any of it.
"""

import io
import tracemalloc
import zipfile

import anyio
import pytest

import main
from src.core.config import settings
from filemakers import make_docx, make_xlsx
from helpers import upload_text

MB = 1024 * 1024
BOUNDARY = "aetherboundary"


def _multipart_body(filename: str, size: int, chunk: int = MB):
    """A multipart upload of a file of `size` bytes, made a chunk at a time as it is read."""
    yield (f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
           "Content-Type: text/plain\r\n\r\n").encode()
    for start in range(0, size, chunk):
        yield b"x" * min(chunk, size - start)
    yield f"\r\n--{BOUNDARY}--\r\n".encode()


def _post_upload(headers: dict, body, declare_length: int | None = None):
    """POST /api/v1/upload straight to the ASGI app. Returns (status, body bytes the app read)."""
    consumed = 0

    async def receive():
        nonlocal consumed
        chunk = next(body, None)
        if chunk is None:
            return {"type": "http.request", "body": b"", "more_body": False}
        consumed += len(chunk)
        return {"type": "http.request", "body": chunk, "more_body": True}

    sent = []

    async def send(message):
        sent.append(message)

    raw = [(b"content-type", f"multipart/form-data; boundary={BOUNDARY}".encode())]
    raw += [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    if declare_length is not None:
        raw.append((b"content-length", str(declare_length).encode()))
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
        "scheme": "http", "path": "/api/v1/upload", "raw_path": b"/api/v1/upload", "root_path": "",
        "query_string": b"", "headers": raw, "client": ("127.0.0.1", 50000), "server": ("testserver", 80),
    }
    anyio.run(main.app, scope, receive, send)
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    return status, consumed


def test_a_60_mb_upload_is_refused_before_any_of_it_is_read(make_user):
    # Sprint 5 "done when". Browsers declare the size of a file upload, so it is refused unread.
    _, headers = make_user("big60")
    size = 60 * MB
    status, consumed = _post_upload(headers, _multipart_body("big.txt", size), declare_length=size + 200)
    assert status == 413
    assert consumed == 0


def test_a_60_mb_upload_that_hides_its_size_is_cut_off_at_the_limit_without_filling_memory(make_user):
    # Without a Content-Length the body is read only up to the limit, and spooled to disk
    _, headers = make_user("big60chunked")
    tracemalloc.start()
    try:
        status, consumed = _post_upload(headers, _multipart_body("big.txt", 60 * MB))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert status == 413
    assert consumed <= settings.max_upload_bytes + 2 * MB  # the 50MB limit and one chunk past it
    assert peak < 8 * MB, f"peak memory while reading the upload: {peak / MB:.1f}MB"


def test_an_upload_without_a_valid_token_is_refused_before_the_body_is_read():
    status, consumed = _post_upload({"Authorization": "Bearer not-a-token"}, _multipart_body("big.txt", 60 * MB),
                                    declare_length=60 * MB + 200)
    assert status == 401
    assert consumed == 0


def test_a_file_just_over_the_limit_is_413_and_one_at_it_is_accepted(client, make_user, monkeypatch):
    _, headers = make_user("edge")
    monkeypatch.setattr(settings, "max_upload_bytes", 200)
    r = upload_text(client, headers, filename="over.txt", text="Zephyr turbine. " * 13)  # 208 bytes
    assert r.status_code == 413 and r.json()["detail"] == "File too large. Maximum allowed: 0MB."
    assert upload_text(client, headers, filename="at.txt", text="z" * 200).status_code == 200


def test_a_body_that_is_not_multipart_is_a_400(client, make_user):
    _, headers = make_user("garbled")
    r = client.post("/api/v1/upload", headers={**headers, "Content-Type": "multipart/form-data"}, content=b"junk")
    assert r.status_code == 400


# ── What a file holds ─────────────────────────────────────────────────────────

def _zip_bomb() -> bytes:
    """A small .docx-named zip whose one entry unpacks to 4MB of zeros."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"\0" * (4 * MB))
    return out.getvalue()


def test_a_zip_based_file_that_unpacks_to_too_much_is_refused_before_it_is_parsed(client, make_user, monkeypatch):
    _, headers = make_user("bomb")
    monkeypatch.setattr(settings, "max_unpacked_bytes", 2 * MB)
    bomb = _zip_bomb()
    assert len(bomb) < 10_000
    r = client.post("/api/v1/upload", headers=headers, files={"file": ("bomb.docx", bomb, "application/octet-stream")})
    assert r.status_code == 422
    assert r.json()["detail"] == ("'bomb.docx' unpacks to more than 2MB, the most one file may hold. "
                                  "Split it into smaller files and upload those.")


def test_a_normal_word_file_is_well_under_the_unpacked_limit(client, make_user, tmp_path):
    _, headers = make_user("docxok")
    data = make_docx(tmp_path / "ok.docx", ["The Zephyr turbine is inspected every 90 days."]).read_bytes()
    r = client.post("/api/v1/upload", headers=headers, files={"file": ("ok.docx", data, "application/octet-stream")})
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("rows,status", [(3, 200), (4, 422)])
def test_a_csv_with_more_rows_than_the_cap_is_refused(client, make_user, monkeypatch, rows, status):
    _, headers = make_user("rows")
    monkeypatch.setattr(settings, "max_table_rows", 3)
    csv = "Part,Bin\n" + "".join(f"P{i},B{i}\n" for i in range(rows))
    r = client.post("/api/v1/upload", headers=headers, files={"file": ("parts.csv", csv.encode(), "text/csv")})
    assert r.status_code == status, r.text
    if status == 422:
        assert "more than 3 rows" in r.json()["detail"]


def test_the_row_cap_counts_every_sheet_of_a_workbook(client, make_user, monkeypatch, tmp_path):
    _, headers = make_user("sheets")
    monkeypatch.setattr(settings, "max_table_rows", 3)
    data = make_xlsx(tmp_path / "two.xlsx", {"A": [["Part"], ["P1"], ["P2"]], "B": [["Bin"], ["B1"], ["B2"]]}).read_bytes()
    r = client.post("/api/v1/upload", headers=headers, files={"file": ("two.xlsx", data, "application/octet-stream")})
    assert r.status_code == 422 and "more than 3 rows" in r.json()["detail"]


def test_a_document_that_makes_too_many_passages_is_refused(client, make_user, monkeypatch):
    _, headers = make_user("chunks")
    monkeypatch.setattr(settings, "max_chunks_per_document", 2)
    text = "\n\n".join(f"Paragraph {i} about the Zephyr turbine maintenance schedule. " * 12 for i in range(6))
    r = upload_text(client, headers, filename="long.txt", text=text)
    assert r.status_code == 422 and "one file may make 2" in r.json()["detail"]
    assert client.get("/api/v1/documents", headers=headers).json()["count"] == 0


# ── Quota ─────────────────────────────────────────────────────────────────────

def test_each_user_has_a_document_quota_and_a_replacement_does_not_count(client, make_user, monkeypatch):
    _, headers = make_user("quota")
    _, other = make_user("quota_other")
    monkeypatch.setattr(settings, "max_documents_per_user", 2)
    assert upload_text(client, headers, filename="a.txt", text="Alpha pumps are serviced monthly.").status_code == 200
    assert upload_text(client, headers, filename="b.txt", text="Beta valves are greased weekly.").status_code == 200

    r = upload_text(client, headers, filename="c.txt", text="Gamma fans are dusted daily.")
    assert r.status_code == 409
    assert r.json()["detail"] == "Your library is full (2 documents). Remove one to add another."

    # A changed file of a name already in the library replaces it, so the count stays at 2
    r = upload_text(client, headers, filename="a.txt", text="Alpha pumps are serviced weekly now.")
    assert r.status_code == 200 and r.json()["replaced"] is True
    # The quota is per user
    assert upload_text(client, other, filename="c.txt", text="Gamma fans are dusted daily.").status_code == 200
