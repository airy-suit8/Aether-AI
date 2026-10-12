"""api/routes_chat.py — ask a question (plain or streamed), feedback, and clearing a session."""

import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from src.api.deps import get_current_user, limiter
from src.api.errors import reference, server_error
from src.api.schemas import ChatRequest, ChatResponse, FeedbackRequest
from src.core.config import settings
from src.core.logging import error_logger, log_event, request_logger
from src.db.database import update_conversation_feedback
from src.memory.conversation import clear_session
from src.pipeline import rag

router = APIRouter()

# Route handlers are plain `def` on purpose: they call blocking code (Gemini, Chroma,
# SQLite, bcrypt), and FastAPI runs `def` handlers in a thread pool, so one slow
# request does not stall every other request.

@router.post("/api/v1/chat", response_model=ChatResponse, tags=["Chat"])
@limiter.limit(settings.rate_limit_chat)
def chat(request: Request, chat_request: ChatRequest, user_id: int = Depends(get_current_user)):
    """Ask a question — answers are grounded in uploaded documents."""
    if not chat_request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    if len(chat_request.question) > settings.max_question_chars:
        raise HTTPException(status_code=400, detail=f"Question too long. Maximum {settings.max_question_chars} characters.")

    mode = chat_request.mode
    start_time = time.time()

    try:
        result = rag.answer(user_id, chat_request.question, session_id=chat_request.session_id, mode=mode)
    except Exception:
        raise server_error(request, "chat_failed", user_id=user_id, mode=mode, session=chat_request.session_id)

    # The question's length is logged, never its text (S10)
    log_event(request_logger, "chat_ok", user_id=user_id, mode=mode, session=chat_request.session_id,
              question_chars=len(chat_request.question), confidence=result.get("confidence"),
              sources=len(result.get("sources", [])), seconds=round(time.time() - start_time, 2))

    return ChatResponse(
        answer=result["answer"],
        sources=result["sources"],
        confidence=result.get("confidence", 0.0),
        session_id=chat_request.session_id,
        tool_used=result.get("tool_used"),
    )


@router.post("/api/v1/feedback", tags=["Chat"])
def submit_feedback(request: Request, feedback_request: FeedbackRequest, user_id: int = Depends(get_current_user)):
    """Submit thumbs up (1) or thumbs down (-1) for the most recent message in the session."""
    try:
        update_conversation_feedback(user_id, feedback_request.session_id, feedback_request.feedback)
    except Exception:
        raise server_error(request, "feedback_failed", user_id=user_id, session=feedback_request.session_id)
    log_event(request_logger, "feedback", user_id=user_id, session=feedback_request.session_id, value=feedback_request.feedback)
    return {"message": "Feedback recorded successfully."}


@router.post("/api/v1/chat/stream", tags=["Chat"])
@limiter.limit(settings.rate_limit_chat)
def chat_stream(request: Request, chat_request: ChatRequest, user_id: int = Depends(get_current_user)):
    """Streaming endpoint — returns the answer token-by-token using SSE."""
    if not chat_request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    if len(chat_request.question) > settings.max_question_chars:
        raise HTTPException(status_code=400, detail=f"Question too long. Maximum {settings.max_question_chars} characters.")

    mode = chat_request.mode
    session = chat_request.session_id
    log_event(request_logger, "stream_request", user_id=user_id, mode=mode, session=session,
              question_chars=len(chat_request.question))
    ref = reference(request)

    # A plain generator: Starlette runs it in a worker thread, so a slow model
    # call does not block the event loop and tokens are sent as they arrive.
    def generate_stream():
        try:
            for event in rag.events(user_id, chat_request.question, session_id=session, mode=mode):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception:
            log_event(error_logger, "stream_failed", level=logging.ERROR, exc_info=True,
                      user_id=user_id, mode=mode, session=session)
            # A separate event type, so the UI shows an error instead of keeping it as an answer
            message = f"The answer could not be generated. Please try again. Reference: {ref}"
            yield f"data: {json.dumps({'type': 'error', 'message': message, 'reference': ref})}\n\n"

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/api/v1/session/clear", tags=["Session"])
def clear_chat_session(chat_request: ChatRequest, user_id: int = Depends(get_current_user)):
    """Clear conversation memory for a session."""
    clear_session(user_id, chat_request.session_id)
    log_event(request_logger, "session_cleared", user_id=user_id, session=chat_request.session_id)
    return {"message": "Session cleared", "session_id": chat_request.session_id}
