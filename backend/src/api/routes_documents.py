"""api/routes_documents.py — upload a document, list a user's documents, delete them."""

import hashlib
import logging
import os
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

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
# request does not stall every other request.

@router.post("/api/v1/upload", response_model=UploadResponse, tags=["Documents"])
@limiter.limit(settings.rate_limit_upload)
def upload_document(request: Request, file: UploadFile = File(...), user_id: int = Depends(get_current_user)):
    """Upload and ingest a PDF or text/markdown document."""
    filename = file.filename or "unknown"
    ext = Path(filename).suffix.lower()

    # Validate file extension
    if ext not in SUPPORTED_EXTENSIONS:
        log_event(upload_logger, "upload_rejected", user_id=user_id, file=filename, reason="type")
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(SUPPORTED_EXTENSIONS)}",
        )

    # Read and validate file content
    try:
        content = file.file.read()
    except Exception:
        raise server_error(request, "upload_read_failed", user_id=user_id, file=filename)

    # Check for empty uploads
    if len(content) == 0:
        log_event(upload_logger, "upload_rejected", user_id=user_id, file=filename, reason="empty")
        raise HTTPException(status_code=400, detail="Uploaded file is empty (0 bytes).")

    # Check file size limit
    if len(content) > settings.max_upload_bytes:
        size_mb = round(len(content) / (1024 * 1024), 1)
        log_event(upload_logger, "upload_rejected", user_id=user_id, file=filename, reason="too_large", bytes=len(content))
        raise HTTPException(
            status_code=400,
            detail=f"File too large ({size_mb}MB). Maximum allowed: {settings.max_upload_bytes // (1024*1024)}MB.",
        )

    # Check for duplicate uploads via file hash
    file_hash = hashlib.sha256(content).hexdigest()
    existing = check_duplicate_document(user_id, file_hash)
    if existing:
        log_event(upload_logger, "upload_rejected", user_id=user_id, file=filename, reason="duplicate", matches=existing)
        # Re-ingesting would store every chunk twice and crowd the top results with copies
        raise HTTPException(
            status_code=409,
            detail=f"This file is already in your library as '{existing}'.",
        )

    # Save to a temp file then ingest
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        start_time = time.time()
        # Stores the chunks and the SQLite record together, and replaces an earlier file of this name
        result = add_document(user_id, tmp_path, filename, len(content), file_hash)
        elapsed = round(time.time() - start_time, 2)

        log_event(upload_logger, "upload_ok", user_id=user_id, file=filename, document_id=result["document_id"],
                  pages=result["pages"], chunks=result["chunks"], bytes=len(content), seconds=elapsed,
                  replaced=result["replaced"])

    except ValueError as e:
        # The message is written for the user and names no server path; the parser's own error,
        # if any, is its cause and goes only to the log
        log_event(error_logger, "upload_unreadable", level=logging.WARNING, user_id=user_id, file=filename,
                  cause=repr(e.__cause__))
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        raise server_error(request, "upload_failed", user_id=user_id, file=filename)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

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
