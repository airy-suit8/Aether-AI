"""Document lifecycle: duplicates are rejected, delete reports what it deleted (R6, R8)."""

import rag_engine
from helpers import DOC_TEXT, upload_text

LONG_TEXT = "\n\n".join(f"Section {i}. " + DOC_TEXT * 4 for i in range(4))  # several chunks


def test_reupload_of_same_file_is_rejected(client, make_user):
    _, headers = make_user("dup")
    first = upload_text(client, headers)
    assert first.status_code == 200

    again = upload_text(client, headers, filename="renamed_copy.txt")
    assert again.status_code == 409
    assert "zephyr_manual.txt" in again.json()["detail"]

    docs = client.get("/api/v1/documents/detailed", headers=headers).json()
    assert docs["count"] == 1


def test_same_file_is_allowed_for_a_different_user(client, make_user):
    _, alice = make_user("dupa")
    _, bob = make_user("dupb")
    assert upload_text(client, alice).status_code == 200
    assert upload_text(client, bob).status_code == 200


def test_delete_returns_the_real_chunk_count(client, make_user):
    _, headers = make_user("del")
    up = upload_text(client, headers, filename="long.txt", text=LONG_TEXT)
    assert up.status_code == 200
    chunks = up.json()["chunks"]
    assert chunks > 1

    r = client.delete("/api/v1/documents", headers=headers)
    assert r.status_code == 200
    assert r.json()["deleted"] == chunks
    assert f"Cleared {chunks} chunks" in r.json()["message"]

    assert client.get("/api/v1/documents", headers=headers).json()["count"] == 0
    again = client.delete("/api/v1/documents", headers=headers)
    assert again.json()["deleted"] == 0


def test_delete_failure_is_reported_and_keeps_the_records(client, make_user, monkeypatch):
    _, headers = make_user("delfail")
    upload_text(client, headers)

    collection = rag_engine._store.chroma._collection

    def broken_delete(*args, **kwargs):
        raise RuntimeError("disk error")

    monkeypatch.setattr(type(collection), "delete", broken_delete)
    r = client.delete("/api/v1/documents", headers=headers)
    assert r.status_code == 500
    # The SQLite records stay, so the document list still matches the vector store
    assert client.get("/api/v1/documents", headers=headers).json()["count"] == 1
