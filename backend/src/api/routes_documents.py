"""api/routes_documents.py — upload a document, list a user's documents, delete them."""

import hashlib
import os
import tempfile
import time
import traceback
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from src.api.deps import get_current_user, limiter
from src.api.schemas import UploadResponse
from src.core.config import settings
from src.core.logging import error_logger, upload_logger
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
        error_logger.error(f"UPLOAD REJECTED | file={filename} | reason=unsupported extension '{ext}'")
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(SUPPORTED_EXTENSIONS)}",
        )

    # Read and validate file content
    try:
        content = file.file.read()
    except Exception as e:
        error_logger.error(f"UPLOAD READ FAILED | file={filename} | error={str(e)}")
        raise HTTPException(status_code=400, detail=f"Could not read uploaded file: {str(e)}")

    # Check for empty uploads
    if len(content) == 0:
        error_logger.error(f"UPLOAD REJECTED | file={filename} | reason=empty file (0 bytes)")
        raise HTTPException(status_code=400, detail="Uploaded file is empty (0 bytes).")

    # Check file size limit
    if len(content) > settings.max_upload_bytes:
        size_mb = round(len(content) / (1024 * 1024), 1)
        error_logger.error(f"UPLOAD REJECTED | file={filename} | reason=too large ({size_mb}MB)")
        raise HTTPException(
            status_code=400,
            detail=f"File too large ({size_mb}MB). Maximum allowed: {settings.max_upload_bytes // (1024*1024)}MB.",
        )

    # Check for duplicate uploads via file hash
    file_hash = hashlib.sha256(content).hexdigest()
    existing = check_duplicate_document(user_id, file_hash)
    if existing:
        upload_logger.info(f"UPLOAD DUPLICATE | user={user_id} | file={filename} | matches={existing}")
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

        # Log successful upload
        upload_logger.info(
            f"UPLOAD OK | user={user_id} | file={filename} | pages={result['pages']} | "
            f"chunks={result['chunks']} | time={elapsed}s | size={len(content)} bytes | replaced={result['replaced']}"
        )

    except ValueError as e:
        # The message is written for the user; the parser's own error, if any, is its cause
        error_logger.error(f"UPLOAD PARSE ERROR | file={filename} | error={str(e)} | cause={e.__cause__!r}")
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        error_logger.error(
            f"UPLOAD INGESTION FAILED | file={filename} | error={str(e)}\n"
            f"{traceback.format_exc()}"
        )
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")
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
def get_documents(user_id: int = Depends(get_current_user)):
    """List all ingested document filenames."""
    try:
        docs = list_documents(user_id)
    except Exception as e:
        error_logger.error(f"DOCUMENT LIST FAILED | error={str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    return {"documents": docs, "count": len(docs)}


@router.get("/api/v1/documents/detailed", tags=["Documents"])
def get_documents_detailed(user_id: int = Depends(get_current_user)):
    """List detailed information of all ingested documents."""
    try:
        docs = get_all_documents_detailed(user_id)
    except Exception as e:
        error_logger.error(f"DOCUMENT DETAILED LIST FAILED | error={str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    return {"documents": docs, "count": len(docs)}


@router.delete("/api/v1/documents/{document_id}", tags=["Documents"])
def delete_one_document(document_id: int, user_id: int = Depends(get_current_user)):
    """Delete one document, by the id the detailed list gives it. 404 for an id that is not yours."""
    try:
        result = delete_document(user_id, document_id)
    except Exception as e:
        error_logger.error(f"DOCUMENT DELETE FAILED | document={document_id} | error={str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    if result is None:
        raise HTTPException(status_code=404, detail="No such document.")
    upload_logger.info(f"DOCUMENT DELETED | user={user_id} | file={result['filename']} | deleted={result['deleted']} chunks")
    return {"message": f"Deleted '{result['filename']}' ({result['deleted']} chunks).", **result}


@router.delete("/api/v1/documents", tags=["Documents"])
def delete_documents(user_id: int = Depends(get_current_user)):
    """Clear all documents from the vector store for the user."""
    try:
        result = clear_documents(user_id)
    except Exception as e:
        error_logger.error(f"DOCUMENT CLEAR FAILED | error={str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    upload_logger.info(f"DOCUMENTS CLEARED | deleted={result['deleted']} chunks")
    return {"message": f"Cleared {result['deleted']} chunks from the vector store.", **result}
