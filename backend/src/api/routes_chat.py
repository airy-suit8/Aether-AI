"""api/routes_chat.py — ask a question (plain or streamed), feedback, and clearing a session."""

import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from src.api.deps import get_current_user, limiter
from src.api.errors import reference, server_error
from src.api.schemas import (
    ChatRequest, ChatResponse, FeedbackRequest, Message, SessionCleared, SessionList, SessionMessages, StreamEvent,
    SESSION_ID_PATTERN,
)
from src.core.config import settings
from src.core.logging import error_logger, log_event, request_logger
from src.db.database import get_session_turns, get_sessions, update_conversation_feedback
from src.llm.llm_client import MODEL_BUSY, is_unavailable
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
    except Exception as e:
        if is_unavailable(e):  # over quota or unavailable, after the retries (B10)
            log_event(error_logger, "chat_model_unavailable", level=logging.WARNING, user_id=user_id, mode=mode)
            raise HTTPException(status_code=503, detail=MODEL_BUSY)
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
        turn_id=result.get("turn_id"),
    )


@router.post("/api/v1/feedback", response_model=Message, tags=["Chat"])
def submit_feedback(request: Request, feedback_request: FeedbackRequest, user_id: int = Depends(get_current_user)):
    """Thumbs up (1), down (-1) or neither (0) for one answer, named by the turn_id it came with
    (F10). 404 for a turn that is not the user's."""
    try:
        found = update_conversation_feedback(user_id, feedback_request.turn_id, feedback_request.feedback)
    except Exception:
        raise server_error(request, "feedback_failed", user_id=user_id, turn_id=feedback_request.turn_id)
    if not found:
        raise HTTPException(status_code=404, detail="No such answer.")
    log_event(request_logger, "feedback", user_id=user_id, turn_id=feedback_request.turn_id, value=feedback_request.feedback)
    return {"message": "Feedback recorded successfully."}


class EventStream(StreamingResponse, JSONResponse):
    """
    Server-sent events. A class of its own so the schema lists the events under text/event-stream.

    It behaves as a StreamingResponse (first in the method order). JSONResponse is a base only so
    that FastAPI describes the stream with the events' models: for any other response class it
    adds "type": "string" to the schema, which contradicts them.
    """
    media_type = "text/event-stream"


STREAM_REPLY = {200: {
    "model": StreamEvent,
    "description": "Server-sent events, one per `data:` line: tokens in order, then one done or one error event.",
}}


@router.post("/api/v1/chat/stream", response_class=EventStream, responses=STREAM_REPLY, tags=["Chat"])
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
        except Exception as e:
            if is_unavailable(e):  # over quota or unavailable, after the retries (B10)
                log_event(error_logger, "stream_model_unavailable", level=logging.WARNING, user_id=user_id, mode=mode)
                message = MODEL_BUSY
            else:
                log_event(error_logger, "stream_failed", level=logging.ERROR, exc_info=True,
                          user_id=user_id, mode=mode, session=session)
                message = f"The answer could not be generated. Please try again. Reference: {ref}"
            # A separate event type, so the UI shows an error instead of keeping it as an answer
            yield f"data: {json.dumps({'type': 'error', 'message': message, 'reference': ref})}\n\n"

    return EventStream(generate_stream(), headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


@router.post("/api/v1/session/clear", response_model=SessionCleared, tags=["Session"])
def clear_chat_session(chat_request: ChatRequest, user_id: int = Depends(get_current_user)):
    """Clear conversation memory for a session."""
    clear_session(user_id, chat_request.session_id)
    log_event(request_logger, "session_cleared", user_id=user_id, session=chat_request.session_id)
    return {"message": "Session cleared", "session_id": chat_request.session_id}


# ── Conversations (Task 5, F8): listed and read back, so a reloaded page can show them again ──

@router.get("/api/v1/sessions", response_model=SessionList, tags=["Session"])
def list_sessions(user_id: int = Depends(get_current_user), limit: int = Query(50, ge=1, le=200)):
    """The user's conversations, most recently used first, each titled by its first question."""
    return {"sessions": get_sessions(user_id, limit)}


@router.get("/api/v1/sessions/{session_id}/messages", response_model=SessionMessages, tags=["Session"])
def session_messages(session_id: str = Path(max_length=100, pattern=SESSION_ID_PATTERN),
                     user_id: int = Depends(get_current_user)):
    """Every turn of one of the user's conversations, oldest first, with the sources and tool
    shown with each answer. Empty for a session with no turns, or one that is not the user's."""
    turns = [{**t, "turn_id": t["id"]} for t in get_session_turns(user_id, session_id)]
    return {"session_id": session_id, "turns": turns}
