"""api/routes_documents.py — upload a document, list a user's documents, delete them."""

import hashlib
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import AsyncIterator, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from starlette.formparsers import MultiPartException, MultiPartParser

from src.api.deps import get_current_user, limiter
from src.api.errors import server_error
from src.api.schemas import UploadResponse
from src.core.config import settings
from src.core.logging import error_logger, log_event, upload_logger
from src.db.database import check_duplicate_document, get_all_documents_detailed
from src.ingestion.loader import SUPPORTED_EXTENSIONS
from src.pipeline.documents import add_document, clear_documents, delete_document, list_documents

router = APIRouter()

# Route handlers are plain `def` on purpose: they call blocking code (Gemini, Chroma,
# SQLite, bcrypt), and FastAPI runs `def` handlers in a thread pool, so one slow
# request does not stall every other request. The upload route is the exception: it reads
# the request body itself, as a stream, and hands the blocking work to the thread pool.

# What a multipart body adds around the file: boundaries and part headers
MULTIPART_ALLOWANCE = 64 * 1024
COPY_CHUNK = 1024 * 1024
NO_FILE = "The request has no file: send it as the multipart form field \"file\"."

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
    filename = upload.filename or "unknown"
    try:
        path, size, file_hash = await run_in_threadpool(_copy_to_temp_file, upload.file, filename)
    finally:
        await upload.close()
    if size > settings.max_upload_bytes:  # within the multipart allowance, but over the limit
        os.unlink(path)
        raise UploadTooLarge
    return filename, path, size, file_hash


@router.post("/api/v1/upload", response_model=UploadResponse, tags=["Documents"], openapi_extra=UPLOAD_BODY)
@limiter.limit(settings.rate_limit_upload)
async def upload_document(request: Request, user_id: int = Depends(get_current_user)):
    """Upload and ingest a document: PDF, Word, text, Markdown, CSV or Excel.

    The token is checked before any of the body is read (S4)."""
    try:
        filename, tmp_path, size, file_hash = await _receive_upload(request)
    except UploadTooLarge:
        log_event(upload_logger, "upload_rejected", user_id=user_id, reason="too_large",
                  declared_bytes=request.headers.get("content-length"))
        raise _too_large()
    except MultiPartException:
        raise HTTPException(status_code=400, detail="The upload could not be read as a file.")

    try:
        return await run_in_threadpool(_ingest_upload, request, user_id, filename, tmp_path, size, file_hash)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _ingest_upload(request: Request, user_id: int, filename: str, tmp_path: str, size: int, file_hash: str) -> UploadResponse:
    """Check the received file against the rules and ingest it. Runs in the thread pool."""
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
    library = get_all_documents_detailed(user_id)
    if len([d for d in library if d["filename"] != filename]) >= settings.max_documents_per_user:
        log_event(upload_logger, "upload_rejected", user_id=user_id, file=filename, reason="quota")
        raise HTTPException(
            status_code=409,
            detail=f"Your library is full ({settings.max_documents_per_user} documents). Remove one to add another.",
        )

    # Check for duplicate uploads via file hash
    existing = check_duplicate_document(user_id, file_hash)
    if existing:
        log_event(upload_logger, "upload_rejected", user_id=user_id, file=filename, reason="duplicate", matches=existing)
        # Re-ingesting would store every chunk twice and crowd the top results with copies
        raise HTTPException(
            status_code=409,
            detail=f"This file is already in your library as '{existing}'.",
        )

    try:
        start_time = time.time()
        # Stores the chunks and the SQLite record together, and replaces an earlier file of this name
        result = add_document(user_id, tmp_path, filename, size, file_hash)
        elapsed = round(time.time() - start_time, 2)
        log_event(upload_logger, "upload_ok", user_id=user_id, file=filename, document_id=result["document_id"],
                  pages=result["pages"], chunks=result["chunks"], bytes=size, seconds=elapsed,
                  replaced=result["replaced"])
    except ValueError as e:
        # The message is written for the user and names no server path; the parser's own error,
        # if any, is its cause and goes only to the log
        log_event(error_logger, "upload_unreadable", level=logging.WARNING, user_id=user_id, file=filename,
                  cause=repr(e.__cause__))
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        raise server_error(request, "upload_failed", user_id=user_id, file=filename)

    msg = f"Successfully ingested '{filename}' ({result['chunks']} chunks from {result['pages']} page(s))."
    if result["replaced"]:
        msg += " It replaced the earlier file of that name."

    return UploadResponse(
        filename=result["filename"],
        pages=result["pages"],
        chunks=result["chunks"],
        message=msg,
        document_id=result["document_id"],
        replaced=result["replaced"],
    )


@router.get("/api/v1/documents", tags=["Documents"])
def get_documents(request: Request, user_id: int = Depends(get_current_user)):
    """List all ingested document filenames."""
    try:
        docs = list_documents(user_id)
    except Exception:
        raise server_error(request, "document_list_failed", user_id=user_id)
    return {"documents": docs, "count": len(docs)}


@router.get("/api/v1/documents/detailed", tags=["Documents"])
def get_documents_detailed(request: Request, user_id: int = Depends(get_current_user)):
    """List detailed information of all ingested documents."""
    try:
        docs = get_all_documents_detailed(user_id)
    except Exception:
        raise server_error(request, "document_list_failed", user_id=user_id)
    return {"documents": docs, "count": len(docs)}


@router.delete("/api/v1/documents/{document_id}", tags=["Documents"])
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


@router.delete("/api/v1/documents", tags=["Documents"])
def delete_documents(request: Request, user_id: int = Depends(get_current_user)):
    """Clear all documents from the vector store for the user."""
    try:
        result = clear_documents(user_id)
    except Exception:
        raise server_error(request, "document_clear_failed", user_id=user_id)
    log_event(upload_logger, "documents_cleared", user_id=user_id, chunks=result["deleted"])
    return {"message": f"Cleared {result['deleted']} chunks from the vector store.", **result}
