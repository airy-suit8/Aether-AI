"""api/routes_documents.py — upload a document, list a user's documents, show one's passages and
its PDF, delete them."""

import hashlib
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import AsyncIterator, Tuple

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path as PathParam, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from starlette.formparsers import MultiPartException, MultiPartParser

from src.api.deps import get_current_user, limiter
from src.api.errors import reference, server_error
from src.api.schemas import (
    DocumentDeleted, DocumentList, DocumentNames, DocumentsCleared, DocumentStatus, PassageView, UploadResponse,
)
from src.core.config import settings
from src.core.logging import error_logger, log_event, upload_logger
from src.db.database import check_duplicate_document, get_all_documents_detailed, get_document, get_tenant_id
from src.ingestion.loader import SUPPORTED_EXTENSIONS, clean_filename
from src.llm.llm_client import is_unavailable, setup_problem
from src.retrieval.scope import documents_of
from src.pipeline.documents import (
    KEPT_KINDS, DocumentRemoved, accept_document, clear_documents, delete_document, fail_document, finish_document,
    has_original, keep_original, list_documents, original_path,
)
from src.vectordb.vector_store import store

router = APIRouter()

# Route handlers are plain `def` on purpose: they call blocking code (Gemini, Chroma,
# SQLite, bcrypt), and FastAPI runs `def` handlers in a thread pool, so one slow
# request does not stall every other request. The upload route is the exception: it reads
# the request body itself, as a stream, and hands the blocking work to the thread pool.

# What a multipart body adds around the file: boundaries and part headers
MULTIPART_ALLOWANCE = 64 * 1024
COPY_CHUNK = 1024 * 1024
NO_FILE = "The request has no file: send it as the multipart form field \"file\"."
NO_ORIGINAL = ("This document's file is not kept, so its pages cannot be shown: only PDFs are, and only those "
               "uploaded since 15 Oct 2026. Upload the same PDF again to keep it; nothing is read twice.")

# The route reads the body itself, so its shape is declared here for the API schema
UPLOAD_BODY = {"requestBody": {"required": True, "content": {"multipart/form-data": {"schema": {
    "type": "object", "required": ["file"], "title": "Upload",
    "properties": {"file": {"type": "string", "format": "binary", "title": "File"}},
}}}}}


class UploadTooLarge(Exception):
    pass


def _too_large() -> HTTPException:
    return HTTPException(
        status_code=413,
        detail=f"File too large. Maximum allowed: {settings.max_upload_bytes // (1024 * 1024)}MB.",
    )


async def _capped(stream: AsyncIterator[bytes], limit: int) -> AsyncIterator[bytes]:
    """The request body, stopping with UploadTooLarge once more than limit bytes have come."""
    received = 0
    async for chunk in stream:
        received += len(chunk)
        if received > limit:
            raise UploadTooLarge
        yield chunk


def _copy_to_temp_file(source, filename: str) -> Tuple[str, int, str]:
    """Copy an upload to a temp file of its own, in chunks. Returns (path, size, sha256)."""
    digest, size = hashlib.sha256(), 0
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(filename).suffix.lower()) as tmp:
        while chunk := source.read(COPY_CHUNK):
            size += len(chunk)
            digest.update(chunk)
            tmp.write(chunk)
    return tmp.name, size, digest.hexdigest()


async def _receive_upload(request: Request) -> Tuple[str, str, int, str]:
    """
    Read the multipart body's "file" part to a temp file, never holding it in memory (S4).
    Returns (filename, temp path, size in bytes, sha256). The caller deletes the temp file.

    A body declared larger than the limit is refused before any of it is read; one that turns
    out larger (no or a false Content-Length) is refused as soon as the limit is passed. The
    parser keeps at most 1MB of a file in memory and spools the rest to disk.
    """
    if not request.headers.get("content-type", "").startswith("multipart/form-data"):
        raise HTTPException(status_code=422, detail=NO_FILE)
    limit = settings.max_upload_bytes + MULTIPART_ALLOWANCE
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise UploadTooLarge
    parser = MultiPartParser(request.headers, _capped(request.stream(), limit), max_files=1, max_fields=10)
    form = await parser.parse()
    upload = form.get("file")
    if upload is None or isinstance(upload, str):
        raise HTTPException(status_code=422, detail=NO_FILE)
    filename = clean_filename(upload.filename or "")  # S5: the name is stored, listed and quoted to the model
    try:
        path, size, file_hash = await run_in_threadpool(_copy_to_temp_file, upload.file, filename)
    finally:
        await upload.close()
    if size > settings.max_upload_bytes:  # within the multipart allowance, but over the limit
        os.unlink(path)
        raise UploadTooLarge
    return filename, path, size, file_hash


@router.post("/api/v1/upload", response_model=UploadResponse, status_code=202, tags=["Documents"],
             openapi_extra=UPLOAD_BODY)
@limiter.limit(settings.rate_limit_upload)
async def upload_document(request: Request, background_tasks: BackgroundTasks, user_id: int = Depends(get_current_user)):
    """Upload a document: PDF, Word, text, Markdown, CSV or Excel. 202: it is accepted and read in
    the background; GET /documents/{document_id} reports when it is ready or why it failed (R12).

    The token is checked before any of the body is read (S4)."""
    try:
        filename, tmp_path, size, file_hash = await _receive_upload(request)
    except UploadTooLarge:
        log_event(upload_logger, "upload_rejected", user_id=user_id, reason="too_large",
                  declared_bytes=request.headers.get("content-length"))
        raise _too_large()
    except MultiPartException:
        raise HTTPException(status_code=400, detail="The upload could not be read as a file.")

    handed_over = False
    try:
        accepted, original_only = await run_in_threadpool(_accept_upload, user_id, filename, size, file_hash)
        if original_only:  # a PDF already read, uploaded again to keep its file: nothing to read
            handed_over = await run_in_threadpool(keep_original, user_id, accepted.document_id, tmp_path, filename)
            log_event(upload_logger, "original_kept", user_id=user_id, document_id=accepted.document_id)
            return accepted
        # Runs after the reply is sent; it deletes the temp file when it is done
        background_tasks.add_task(_read_in_background, user_id, accepted.document_id, tmp_path, filename,
                                  size, reference(request))
        handed_over = True
        return accepted
    finally:
        if not handed_over and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _accept_upload(user_id: int, filename: str, size: int, file_hash: str) -> Tuple[UploadResponse, bool]:
    """Check the received file against the rules and record it as processing. Runs in the thread pool.
    Returns the reply, and whether the file is only to be kept as the original of a document already
    read: a PDF uploaded before originals were kept, uploaded again."""
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        log_event(upload_logger, "upload_rejected", user_id=user_id, file=filename, reason="type")
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(SUPPORTED_EXTENSIONS)}",
        )

    if size == 0:
        log_event(upload_logger, "upload_rejected", user_id=user_id, file=filename, reason="empty")
        raise HTTPException(status_code=400, detail="Uploaded file is empty (0 bytes).")

    # A per-user quota. A file that replaces one of the same name does not add to the count.
    library = [d for d in get_all_documents_detailed(user_id) if d["status"] != "failed"]
    if len([d for d in library if d["filename"] != filename]) >= settings.max_documents_per_user:
        log_event(upload_logger, "upload_rejected", user_id=user_id, file=filename, reason="quota")
        raise HTTPException(
            status_code=409,
            detail=f"Your library is full ({settings.max_documents_per_user} documents). Remove one to add another.",
        )

    # Check for duplicate uploads via file hash
    existing = check_duplicate_document(user_id, file_hash)
    if existing:
        if ext in KEPT_KINDS and existing["status"] == "ready" and not has_original(user_id, existing["id"]):
            return UploadResponse(
                document_id=existing["id"], filename=existing["filename"], status="ready", replaces=False,
                message=f"Kept the file of '{existing['filename']}', to show its pages.",
            ), True
        log_event(upload_logger, "upload_rejected", user_id=user_id, file=filename, reason="duplicate",
                  matches=existing["filename"])
        # Re-ingesting would store every chunk twice and crowd the top results with copies
        raise HTTPException(
            status_code=409,
            detail=f"This file is already in your library as '{existing['filename']}'.",
        )

    accepted = accept_document(user_id, filename, size, file_hash)
    log_event(upload_logger, "upload_accepted", user_id=user_id, file=filename, document_id=accepted["document_id"],
              bytes=size)
    return UploadResponse(
        document_id=accepted["document_id"],
        filename=filename,
        replaces=accepted["replaces"],
        message=f"Reading '{filename}'.",
    ), False


def _read_in_background(user_id: int, document_id: int, tmp_path: str, filename: str, size: int, ref: str) -> None:
    """Read an accepted upload into the vector store, then delete its temp file (R12).

    FastAPI runs it after the 202 is sent, in the thread pool. Whatever happens, the document
    ends "ready" or "failed", and a failure's message is one its owner can read: the parser's
    own error, which can name a server path, and any other exception go only to the log.
    """
    start_time = time.time()
    try:
        result = finish_document(user_id, document_id, tmp_path, filename)
        try:  # a PDF, to show its pages; the document is read either way
            kept = keep_original(user_id, document_id, tmp_path, filename)
        except OSError:
            kept = False
            log_event(error_logger, "original_not_kept", level=logging.WARNING, exc_info=True, user_id=user_id,
                      document_id=document_id)
        log_event(upload_logger, "upload_ok", user_id=user_id, file=filename, document_id=document_id,
                  pages=result["pages"], chunks=result["chunks"], bytes=size,
                  seconds=round(time.time() - start_time, 2), replaced=result["replaced"], original_kept=kept)
    except DocumentRemoved:
        log_event(upload_logger, "upload_removed_while_read", user_id=user_id, file=filename, document_id=document_id)
    except ValueError as e:
        # DocumentError, or no text to extract: the message is written for the user
        log_event(error_logger, "upload_unreadable", level=logging.WARNING, user_id=user_id, file=filename,
                  document_id=document_id, cause=repr(e.__cause__))
        fail_document(user_id, document_id, str(e))
    except Exception as e:
        if is_unavailable(e):  # the embedding service was over its quota or unavailable (B10)
            log_event(error_logger, "upload_model_unavailable", level=logging.WARNING, user_id=user_id,
                      file=filename, document_id=document_id)
            fail_document(user_id, document_id, "The AI service was busy or over its usage limit while reading "
                          "this file. Please upload it again in a minute.")
            return
        problem = setup_problem(e)
        if problem:  # something the owner must fix on this computer, such as Ollama not running
            log_event(error_logger, "upload_model_setup", level=logging.ERROR, user_id=user_id,
                      file=filename, document_id=document_id, cause=repr(e))
            fail_document(user_id, document_id, problem)
            return
        log_event(error_logger, "upload_failed", level=logging.ERROR, exc_info=True, user_id=user_id,
                  file=filename, document_id=document_id)
        fail_document(user_id, document_id,
                      f"Something went wrong on the server while reading this file. Please try again. Reference: {ref}")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@router.get("/api/v1/documents", response_model=DocumentNames, tags=["Documents"])
def get_documents(request: Request, user_id: int = Depends(get_current_user)):
    """List all ingested document filenames."""
    try:
        docs = list_documents(user_id)
    except Exception:
        raise server_error(request, "document_list_failed", user_id=user_id)
    return {"documents": docs, "count": len(docs)}


@router.get("/api/v1/documents/detailed", response_model=DocumentList, tags=["Documents"])
def get_documents_detailed(request: Request, user_id: int = Depends(get_current_user)):
    """List detailed information of all ingested documents."""
    try:
        docs = get_all_documents_detailed(user_id)
        named = {d.id: d for d in documents_of(user_id)}  # titles and kinds, for "Search in"
    except Exception:
        raise server_error(request, "document_list_failed", user_id=user_id)
    for doc in docs:
        if doc["id"] in named:
            doc["title"], doc["kind"] = named[doc["id"]].title or None, named[doc["id"]].kind
    return {"documents": docs, "count": len(docs)}


@router.get("/api/v1/documents/{document_id}", response_model=DocumentStatus, tags=["Documents"])
def get_one_document(document_id: int, user_id: int = Depends(get_current_user)):
    """One document and how reading it went: "processing", then "ready" or "failed" with an error
    (R12). 404 for an id that is not yours. Declared after /documents/detailed, which it would
    otherwise shadow."""
    document = get_document(user_id, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="No such document.")
    return document


@router.get("/api/v1/documents/{document_id}/passages/{passage}", response_model=PassageView, tags=["Documents"])
def get_passage(document_id: int, passage: int = PathParam(ge=1), around: int = Query(default=1, ge=0, le=3),
                user_id: int = Depends(get_current_user)):
    """One passage of a document, numbered from 1 as sources give it, with `around` passages either
    side, in order: a source shown in its place. Says whether the document's PDF is kept, to show
    its page. 404 for a document that is not yours, or a passage it does not have."""
    document = get_document(user_id, document_id)
    if document is None or document["status"] != "ready":
        raise HTTPException(status_code=404, detail="No such document.")
    items = store.passages_at(get_tenant_id(user_id), document_id, list(range(passage - around, passage + around + 1)))
    if not any(meta.get("chunk_index") == passage for _, meta in items):
        raise HTTPException(status_code=404, detail="That document has no such passage.")
    first = items[0][1]
    return {
        "document_id": document_id, "filename": document["filename"], "kind": first.get("type"),
        "passages": first.get("total_chunks") or document["chunks"], "original": has_original(user_id, document_id),
        "items": [{"passage": meta["chunk_index"], "page": meta.get("page", "?"), "text": text} for text, meta in items],
    }


@router.get("/api/v1/documents/{document_id}/file", response_class=FileResponse, tags=["Documents"],
            responses={200: {"content": {"application/pdf": {}}, "description": "The PDF as it was uploaded"}})
# Its own limit, the default rate: a route the rate limiter's middleware handles has its reply's
# start sent again before each 64 KB piece of the file, which ends the reply at the first (D-077)
@limiter.limit(settings.rate_limit_default)
def get_document_file(request: Request, document_id: int, user_id: int = Depends(get_current_user)):
    """A document's PDF as it was uploaded, to show a source on its page. 404 for a document that
    is not yours, and for one whose file is not kept (not a PDF, or uploaded before 15 Oct 2026)."""
    document = get_document(user_id, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="No such document.")
    if not has_original(user_id, document_id):
        raise HTTPException(status_code=404, detail=NO_ORIGINAL)
    return FileResponse(original_path(user_id, document_id), media_type="application/pdf",
                        filename=document["filename"], content_disposition_type="inline")


@router.delete("/api/v1/documents/{document_id}", response_model=DocumentDeleted, tags=["Documents"])
def delete_one_document(request: Request, document_id: int, user_id: int = Depends(get_current_user)):
    """Delete one document, by the id the detailed list gives it. 404 for an id that is not yours."""
    try:
        result = delete_document(user_id, document_id)
    except Exception:
        raise server_error(request, "document_delete_failed", user_id=user_id, document_id=document_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No such document.")
    log_event(upload_logger, "document_deleted", user_id=user_id, document_id=document_id, chunks=result["deleted"])
    return {"message": f"Deleted '{result['filename']}' ({result['deleted']} chunks).", **result}


@router.delete("/api/v1/documents", response_model=DocumentsCleared, tags=["Documents"])
def delete_documents(request: Request, user_id: int = Depends(get_current_user)):
    """Clear all documents from the vector store for the user."""
    try:
        result = clear_documents(user_id)
    except Exception:
        raise server_error(request, "document_clear_failed", user_id=user_id)
    log_event(upload_logger, "documents_cleared", user_id=user_id, chunks=result["deleted"])
    return {"message": f"Cleared {result['deleted']} chunks from the vector store.", **result}
