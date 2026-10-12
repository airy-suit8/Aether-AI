"""
Document lifecycle: duplicates are rejected, delete reports what it deleted (R6, R8), and each
document can be deleted or replaced on its own (R7).
"""

import jwt
from langchain_core.documents import Document

from src.db import database
from src.pipeline import documents
from src.vectordb import vector_store
from helpers import DOC_TEXT, ask, tenant_of, upload_text

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

    collection = vector_store.store.chroma._collection

    def broken_delete(*args, **kwargs):
        raise RuntimeError("disk error")

    monkeypatch.setattr(type(collection), "delete", broken_delete)
    r = client.delete("/api/v1/documents", headers=headers)
    assert r.status_code == 500
    # The SQLite records stay, so the document list still matches the vector store
    assert client.get("/api/v1/documents", headers=headers).json()["count"] == 1


# ── One document at a time (R7) ───────────────────────────────────────────────

CANTEEN = "Lunch is served in the canteen at noon. The canteen is closed on Sundays."


def _user_id(headers):
    return int(jwt.decode(headers["Authorization"].split()[1], options={"verify_signature": False})["sub"])


def _chunks(headers):
    """The metadata of every chunk this user has in the vector store."""
    return vector_store.store.collection.get(where={"tenant_id": tenant_of(headers)}, include=["metadatas"])["metadatas"]


def _listed(client, headers):
    return {d["filename"]: d["id"] for d in client.get("/api/v1/documents/detailed", headers=headers).json()["documents"]}


def test_every_chunk_carries_its_document_s_id(client, make_user):
    _, headers = make_user("docid")
    document_id = upload_text(client, headers, filename="long.txt", text=LONG_TEXT).json()["document_id"]
    assert _listed(client, headers) == {"long.txt": document_id}
    metas = _chunks(headers)
    assert len(metas) > 1 and {m["document_id"] for m in metas} == {document_id}


def test_one_document_is_deleted_and_the_other_stays(client, make_user):
    _, headers = make_user("delone")
    document_id = upload_text(client, headers, filename="long.txt", text=LONG_TEXT).json()["document_id"]
    chunks = len(_chunks(headers))
    upload_text(client, headers, filename="canteen.txt", text=CANTEEN)

    r = client.delete(f"/api/v1/documents/{document_id}", headers=headers)
    assert r.status_code == 200
    assert r.json() == {"message": f"Deleted 'long.txt' ({chunks} chunks).", "filename": "long.txt", "deleted": chunks}
    assert list(_listed(client, headers)) == ["canteen.txt"]
    assert [m["source"] for m in _chunks(headers)] == ["canteen.txt"]

    assert client.delete(f"/api/v1/documents/{document_id}", headers=headers).status_code == 404  # already gone


def test_a_deleted_document_can_no_longer_be_found_by_a_question(client, make_user):
    _, headers = make_user("delask")
    document_id = upload_text(client, headers).json()["document_id"]
    upload_text(client, headers, filename="canteen.txt", text=CANTEEN)
    question = "How often is the Zephyr turbine blade inspection?"
    for mode in ("default", "hybrid"):
        assert "zephyr_manual.txt" in [s["source"] for s in ask(client, headers, question, mode=mode).json()["sources"]]
    client.delete(f"/api/v1/documents/{document_id}", headers=headers)
    for mode in ("default", "hybrid"):  # hybrid too: its keyword index is rebuilt after a delete
        assert "zephyr_manual.txt" not in [s["source"] for s in ask(client, headers, question, mode=mode).json()["sources"]]


def test_another_user_s_document_cannot_be_deleted(client, make_user):
    _, alice = make_user("dela")
    _, bob = make_user("delb")
    document_id = upload_text(client, alice).json()["document_id"]
    r = client.delete(f"/api/v1/documents/{document_id}", headers=bob)
    assert r.status_code == 404 and r.json()["detail"] == "No such document."
    assert _listed(client, alice) == {"zephyr_manual.txt": document_id} and len(_chunks(alice)) == 1


def test_an_id_that_is_not_a_number_is_a_422(client, make_user):
    _, headers = make_user("delbad")
    document_id = "not-a-number"
    assert client.delete(f"/api/v1/documents/{document_id}", headers=headers).status_code == 422


def test_uploading_a_changed_file_of_the_same_name_replaces_it(client, make_user):
    _, headers = make_user("replace")
    first = upload_text(client, headers, filename="policy.txt", text="The notice period is 30 days.").json()
    assert first["replaced"] is False

    second = upload_text(client, headers, filename="policy.txt", text="The notice period is 60 days.")
    assert second.status_code == 200
    assert second.json()["replaced"] is True and second.json()["document_id"] != first["document_id"]
    assert second.json()["message"].endswith("It replaced the earlier file of that name.")
    assert _listed(client, headers) == {"policy.txt": second.json()["document_id"]}
    answer = ask(client, headers, "What is the notice period?").json()
    assert "60 days" in answer["answer"] and "30 days" not in answer["answer"]
    assert {m["document_id"] for m in _chunks(headers)} == {second.json()["document_id"]}


def test_a_replacement_that_fails_keeps_the_earlier_file(client, make_user, monkeypatch):
    _, headers = make_user("keepold")
    first = upload_text(client, headers, filename="policy.txt", text="The notice period is 30 days.").json()

    def broken(*args, **kwargs):
        raise RuntimeError("embedding service down")

    monkeypatch.setattr(documents, "ingest_document", broken)
    assert upload_text(client, headers, filename="policy.txt", text="The notice period is 60 days.").status_code == 500
    assert _listed(client, headers) == {"policy.txt": first["document_id"]}
    assert {m["document_id"] for m in _chunks(headers)} == {first["document_id"]}


def test_a_document_stored_before_documents_had_ids_can_be_deleted(client, make_user):
    # Chunks ingested before Sprint 4 carry the file name but no document_id
    _, headers = make_user("legacy")
    user_id, tenant = _user_id(headers), tenant_of(headers)
    vector_store.store.add_documents(tenant, [
        Document(page_content=f"Old chunk {i} of the turbine manual.", metadata={"source": "old.txt", "page": 1, "chunk_id": f"old-{user_id}-{i}"})
        for i in range(3)])
    old_id = database.save_document_record(user_id, "old.txt", pages=1, chunks=3)
    new_id = upload_text(client, headers, filename="old.txt", text="A newer file that happens to share the name.").json()["document_id"]
    # Uploading the name again replaced the old one: its three chunks went, the new chunk stayed
    assert old_id not in _listed(client, headers).values()
    assert [m.get("document_id") for m in _chunks(headers)] == [new_id]

    vector_store.store.add_documents(tenant, [
        Document(page_content="Another old chunk.", metadata={"source": "older.txt", "page": 1, "chunk_id": f"older-{user_id}"})])
    document_id = database.save_document_record(user_id, "older.txt", pages=1, chunks=1)
    r = client.delete(f"/api/v1/documents/{document_id}", headers=headers)
    assert r.json()["deleted"] == 1
    assert [m["source"] for m in _chunks(headers)] == ["old.txt"]


def test_a_failed_delete_of_one_document_is_reported_and_keeps_its_record(client, make_user, monkeypatch):
    _, headers = make_user("delonefail")
    document_id = upload_text(client, headers).json()["document_id"]

    def broken_delete(*args, **kwargs):
        raise RuntimeError("disk error")

    monkeypatch.setattr(type(vector_store.store.chroma._collection), "delete", broken_delete)
    assert client.delete(f"/api/v1/documents/{document_id}", headers=headers).status_code == 500
    assert _listed(client, headers) == {"zephyr_manual.txt": document_id}


def test_upload_with_the_langchain_loader_cites_pages_from_one(client, make_user, monkeypatch, tmp_path):
    # Task 12 through the API: the LangChain loaders sit behind the same upload route
    from filemakers import make_pdf
    from src.core.config import settings

    _, headers = make_user("lcload")
    monkeypatch.setattr(settings, "document_loader", "langchain")
    pdf = make_pdf(tmp_path / "two.pdf", ["The Zephyr turbine page", "The Orion team page"]).read_bytes()
    r = client.post("/api/v1/upload", headers=headers, files={"file": ("two.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text
    assert r.json()["pages"] == 2
    metas = _chunks(headers)
    assert sorted(m["page"] for m in metas) == [1, 2]
