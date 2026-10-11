"""
main.py — FastAPI application for the RAG Chatbot (Aether AI)
Endpoints:
  POST /upload       — ingest a document
  POST /chat         — ask a question (RAG)
  POST /chat/stream  — ask a question with streaming (Task 18)
  GET  /documents    — list ingested documents
  DELETE /documents  — clear all documents
  GET  /health       — health check endpoint
"""

import os
import time
import hashlib
import tempfile
import traceback
from pathlib import Path
from datetime import datetime, timedelta

from fastapi import FastAPI, File, UploadFile, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, field_validator

# Rate limiting
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from rag_engine import ingest_document, query_rag, query_rag_stream, list_documents, clear_documents, clear_session
from rag_langchain import query_rag_langchain, query_rag_langchain_stream, ingest_document_langchain
from agent import run_agent

# Task 16: Logging
from logger import request_logger, upload_logger, error_logger

# SQLite persistence
from database import (
    save_document_record,
    check_duplicate_document,
    get_conversation_stats,
    get_document_stats,
    get_all_documents_detailed,
    update_conversation_feedback,
    get_user_by_username,
    create_user,
)

from auth import get_current_user, create_access_token, verify_password, get_password_hash, ACCESS_TOKEN_EXPIRE_MINUTES

# ── Rate Limiter ──────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)

# ── App setup ─────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Aether AI — Knowledge Assistant API",
    description="A Retrieval-Augmented Generation chatbot powered by Google Gemini",
    version="2.0.0",
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

_start_time = datetime.now()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md", ".markdown", ".docx", ".csv", ".xlsx", ".xls"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB max upload size

# ── Request/Response Models ────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    question: str
    session_id: str = "default"
    use_agent: bool = False
    use_langchain: bool = False
    use_hybrid: bool = False

class ChatResponse(BaseModel):
    answer: str
    sources: list
    confidence: float = 0.0
    session_id: str = "default"

class FeedbackRequest(BaseModel):
    session_id: str
    feedback: int  # 1 for up, -1 for down, 0 to clear

class UploadResponse(BaseModel):
    filename: str
    pages: int
    chunks: int
    message: str

class UserRegister(BaseModel):
    username: str
    password: str

    @field_validator('username')
    @classmethod
    def username_valid(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3:
            raise ValueError('Username must be at least 3 characters')
        if len(v) > 50:
            raise ValueError('Username must be at most 50 characters')
        if not v.isalnum() and not all(c.isalnum() or c in '_-' for c in v):
            raise ValueError('Username may only contain letters, digits, hyphens, and underscores')
        return v

    @field_validator('password')
    @classmethod
    def password_valid(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError('Password must be at least 6 characters')
        if len(v) > 128:
            raise ValueError('Password must be at most 128 characters')
        return v

class Token(BaseModel):
    access_token: str
    token_type: str

# ── Authentication ────────────────────────────────────────────────────────────

@app.post("/api/v1/auth/register", tags=["Auth"])
@limiter.limit("5/minute")
async def register(user: UserRegister, request: Request):
    if get_user_by_username(user.username):
        raise HTTPException(status_code=400, detail="Username already registered")
    hashed_password = get_password_hash(user.password)
    user_id = create_user(user.username, hashed_password)
    return {"message": "User registered successfully", "user_id": user_id}

@app.post("/api/v1/auth/login", response_model=Token, tags=["Auth"])
@limiter.limit("10/minute")
async def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):
    user = get_user_by_username(form_data.username)
    if not user or not verify_password(form_data.password, user["password_hash"]):
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user["id"])}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


# ── Health Check ──────────────────────────────────────────────────────────────

@app.get("/api/v1/health", tags=["System"])
async def health_check():
    """Health check endpoint for monitoring and load balancers."""
    uptime = (datetime.now() - _start_time).total_seconds()
    doc_stats = get_document_stats()
    conv_stats = get_conversation_stats()
    return {
        "status": "ok",
        "version": "2.0.0",
        "uptime_seconds": round(uptime, 1),
        "documents": doc_stats,
        "conversations": conv_stats,
    }


# ── Upload ────────────────────────────────────────────────────────────────────

@app.post("/api/v1/upload", response_model=UploadResponse, tags=["Documents"])
@limiter.limit("10/minute")
async def upload_document(request: Request, file: UploadFile = File(...), user_id: int = Depends(get_current_user)):
    """Upload and ingest a PDF or text/markdown document."""
    filename = file.filename or "unknown"
    ext = Path(filename).suffix.lower()

    # Validate file extension
    if ext not in ALLOWED_EXTENSIONS:
        error_logger.error(f"UPLOAD REJECTED | file={filename} | reason=unsupported extension '{ext}'")
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    # Read and validate file content
    try:
        content = await file.read()
    except Exception as e:
        error_logger.error(f"UPLOAD READ FAILED | file={filename} | error={str(e)}")
        raise HTTPException(status_code=400, detail=f"Could not read uploaded file: {str(e)}")

    # Check for empty uploads
    if len(content) == 0:
        error_logger.error(f"UPLOAD REJECTED | file={filename} | reason=empty file (0 bytes)")
        raise HTTPException(status_code=400, detail="Uploaded file is empty (0 bytes).")

    # Check file size limit
    if len(content) > MAX_FILE_SIZE:
        size_mb = round(len(content) / (1024 * 1024), 1)
        error_logger.error(f"UPLOAD REJECTED | file={filename} | reason=too large ({size_mb}MB)")
        raise HTTPException(
            status_code=400,
            detail=f"File too large ({size_mb}MB). Maximum allowed: {MAX_FILE_SIZE // (1024*1024)}MB.",
        )

    # Check for duplicate uploads via file hash
    file_hash = hashlib.sha256(content).hexdigest()
    existing = check_duplicate_document(user_id, file_hash)
    if existing:
        upload_logger.info(f"UPLOAD DUPLICATE | user={user_id} | file={filename} | matches={existing}")
        # Allow re-upload but warn
        # (don't block — user might want to update)

    # Save to a temp file then ingest
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        start_time = time.time()
        result = ingest_document(user_id, tmp_path, filename)
        elapsed = round(time.time() - start_time, 2)

        # Log successful upload
        upload_logger.info(
            f"UPLOAD OK | user={user_id} | file={filename} | pages={result['pages']} | "
            f"chunks={result['chunks']} | time={elapsed}s | size={len(content)} bytes"
        )

        # Save to SQLite
        save_document_record(user_id, filename, result["pages"], result["chunks"], len(content), file_hash)

    except ValueError as e:
        error_logger.error(f"UPLOAD PARSE ERROR | file={filename} | error={str(e)}")
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
    if existing:
        msg += f" Note: This file was previously uploaded as '{existing}'."

    return UploadResponse(
        filename=result["filename"],
        pages=result["pages"],
        chunks=result["chunks"],
        message=msg,
    )


# ── Chat ──────────────────────────────────────────────────────────────────────

@app.post("/api/v1/chat", response_model=ChatResponse, tags=["Chat"])
@limiter.limit("30/minute")
async def chat(request: Request, chat_request: ChatRequest, user_id: int = Depends(get_current_user)):
    """Ask a question — answers are grounded in uploaded documents."""
    if not chat_request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    if len(chat_request.question) > 5000:
        raise HTTPException(status_code=400, detail="Question too long. Maximum 5000 characters.")

    mode = "agent" if chat_request.use_agent else ("langchain" if chat_request.use_langchain else "original")
    start_time = time.time()

    try:
        if chat_request.use_agent:
            result = run_agent(user_id, chat_request.question, session_id=chat_request.session_id)
        elif chat_request.use_langchain:
            result = query_rag_langchain(user_id, chat_request.question, session_id=chat_request.session_id)
        else:
            result = query_rag(user_id, chat_request.question, session_id=chat_request.session_id, use_hybrid=chat_request.use_hybrid)
    except Exception as e:
        error_logger.error(
            f"CHAT FAILED | mode={mode} | session={chat_request.session_id} | "
            f"question={chat_request.question[:100]} | error={str(e)}\n"
            f"{traceback.format_exc()}"
        )
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")

    elapsed = round(time.time() - start_time, 2)

    request_logger.info(
        f"CHAT OK | mode={mode} | session={chat_request.session_id} | "
        f"question={chat_request.question[:80]} | confidence={result.get('confidence', 0)} | "
        f"sources={len(result.get('sources', []))} | time={elapsed}s"
    )

    return ChatResponse(
        answer=result["answer"],
        sources=result["sources"],
        confidence=result.get("confidence", 0.0),
        session_id=chat_request.session_id,
    )


@app.post("/api/v1/feedback", tags=["Chat"])
async def submit_feedback(feedback_request: FeedbackRequest, user_id: int = Depends(get_current_user)):
    """Submit thumbs up (1) or thumbs down (-1) for the most recent message in the session."""
    try:
        update_conversation_feedback(user_id, feedback_request.session_id, feedback_request.feedback)
        request_logger.info(f"FEEDBACK LOGGED | session={feedback_request.session_id} | value={feedback_request.feedback}")
        return {"message": "Feedback recorded successfully."}
    except Exception as e:
        error_logger.error(f"FEEDBACK FAILED | session={feedback_request.session_id} | error={str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to record feedback: {str(e)}")


# ── Streaming ─────────────────────────────────────────────────────────────────

@app.post("/api/v1/chat/stream", tags=["Chat"])
@limiter.limit("30/minute")
async def chat_stream(request: Request, chat_request: ChatRequest, user_id: int = Depends(get_current_user)):
    """Streaming endpoint — returns the answer token-by-token using SSE."""
    if not chat_request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    mode = "agent" if chat_request.use_agent else ("langchain" if chat_request.use_langchain else "original")

    request_logger.info(f"STREAM REQUEST | mode={mode} | question={chat_request.question[:80]}")

    import json

    async def generate_stream():
        try:
            if chat_request.use_agent:
                # Agent doesn't have a streaming LCEL pipeline in this architecture yet, fallback to fake streaming
                result = run_agent(user_id, chat_request.question, session_id=chat_request.session_id)
                answer = result["answer"]
                words = answer.split(" ")
                for i, word in enumerate(words):
                    token = word if i == 0 else " " + word
                    yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'sources': result.get('sources', []), 'confidence': result.get('confidence', 0.0), 'tool_used': result.get('tool_used', None)})}\n\n"
            elif chat_request.use_langchain:
                for chunk in query_rag_langchain_stream(user_id, chat_request.question, session_id=chat_request.session_id):
                    yield f"data: {json.dumps(chunk)}\n\n"
            else:
                for chunk in query_rag_stream(user_id, chat_request.question, session_id=chat_request.session_id, use_hybrid=chat_request.use_hybrid):
                    yield f"data: {json.dumps(chunk)}\n\n"
        except Exception as e:
            error_logger.error(f"STREAM FAILED | mode={mode} | error={str(e)}")
            yield f"data: {json.dumps({'type': 'token', 'content': f'An error occurred: {str(e)}'})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'sources': [], 'confidence': 0.0})}\n\n"

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# ── Session ───────────────────────────────────────────────────────────────────

@app.post("/api/v1/session/clear", tags=["Session"])
async def clear_chat_session(chat_request: ChatRequest, user_id: int = Depends(get_current_user)):
    """Clear conversation memory for a session."""
    clear_session(user_id, chat_request.session_id)
    request_logger.info(f"SESSION CLEARED | session={chat_request.session_id}")
    return {"message": "Session cleared", "session_id": chat_request.session_id}


# ── Documents ─────────────────────────────────────────────────────────────────

@app.get("/api/v1/documents", tags=["Documents"])
async def get_documents(user_id: int = Depends(get_current_user)):
    """List all ingested document filenames."""
    try:
        docs = list_documents(user_id)
    except Exception as e:
        error_logger.error(f"DOCUMENT LIST FAILED | error={str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    return {"documents": docs, "count": len(docs)}


@app.get("/api/v1/documents/detailed", tags=["Documents"])
async def get_documents_detailed(user_id: int = Depends(get_current_user)):
    """List detailed information of all ingested documents."""
    try:
        docs = get_all_documents_detailed(user_id)
    except Exception as e:
        error_logger.error(f"DOCUMENT DETAILED LIST FAILED | error={str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    return {"documents": docs, "count": len(docs)}


@app.delete("/api/v1/documents", tags=["Documents"])
async def delete_documents(user_id: int = Depends(get_current_user)):
    """Clear all documents from the vector store for the user."""
    try:
        result = clear_documents(user_id)
    except Exception as e:
        error_logger.error(f"DOCUMENT CLEAR FAILED | error={str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    upload_logger.info(f"DOCUMENTS CLEARED | deleted={result['deleted']} chunks")
    return {"message": f"Cleared {result['deleted']} chunks from the vector store.", **result}
