"""api/routes_chat.py — ask a question (plain or streamed), feedback, and clearing a session."""

import json
import time
import traceback

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from src.api.deps import get_current_user, limiter
from src.api.schemas import ChatRequest, ChatResponse, FeedbackRequest
from src.core.config import settings
from src.core.logging import error_logger, request_logger
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

    mode = chat_request.mode()
    start_time = time.time()

    try:
        result = rag.answer(user_id, chat_request.question, session_id=chat_request.session_id, mode=mode)
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
        tool_used=result.get("tool_used"),
    )


@router.post("/api/v1/feedback", tags=["Chat"])
def submit_feedback(feedback_request: FeedbackRequest, user_id: int = Depends(get_current_user)):
    """Submit thumbs up (1) or thumbs down (-1) for the most recent message in the session."""
    try:
        update_conversation_feedback(user_id, feedback_request.session_id, feedback_request.feedback)
        request_logger.info(f"FEEDBACK LOGGED | session={feedback_request.session_id} | value={feedback_request.feedback}")
        return {"message": "Feedback recorded successfully."}
    except Exception as e:
        error_logger.error(f"FEEDBACK FAILED | session={feedback_request.session_id} | error={str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to record feedback: {str(e)}")


@router.post("/api/v1/chat/stream", tags=["Chat"])
@limiter.limit(settings.rate_limit_chat)
def chat_stream(request: Request, chat_request: ChatRequest, user_id: int = Depends(get_current_user)):
    """Streaming endpoint — returns the answer token-by-token using SSE."""
    if not chat_request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    if len(chat_request.question) > settings.max_question_chars:
        raise HTTPException(status_code=400, detail=f"Question too long. Maximum {settings.max_question_chars} characters.")

    mode = chat_request.mode()

    request_logger.info(f"STREAM REQUEST | mode={mode} | question={chat_request.question[:80]}")

    # A plain generator: Starlette runs it in a worker thread, so a slow model
    # call does not block the event loop and tokens are sent as they arrive.
    def generate_stream():
        try:
            for event in rag.events(user_id, chat_request.question, session_id=chat_request.session_id, mode=mode):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            error_logger.error(f"STREAM FAILED | mode={mode} | error={str(e)}\n{traceback.format_exc()}")
            # A separate event type, so the UI shows an error instead of keeping it as an answer
            yield f"data: {json.dumps({'type': 'error', 'message': 'The answer could not be generated. Please try again.'})}\n\n"

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/api/v1/session/clear", tags=["Session"])
def clear_chat_session(chat_request: ChatRequest, user_id: int = Depends(get_current_user)):
    """Clear conversation memory for a session."""
    clear_session(user_id, chat_request.session_id)
    request_logger.info(f"SESSION CLEARED | session={chat_request.session_id}")
    return {"message": "Session cleared", "session_id": chat_request.session_id}
