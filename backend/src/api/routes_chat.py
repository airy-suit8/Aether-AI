"""api/routes_chat.py — ask a question (plain or streamed), feedback, and clearing a session."""

import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from src.api.deps import get_current_user, limiter
from src.api.errors import reference, server_error
from src.api.schemas import (
    ChatRequest, ChatResponse, FeedbackRequest, Message, SessionCleared, SessionList, SessionMessages, SessionRename,
    SessionTitle, SharedConversation, ShareState, StreamEvent, SESSION_ID_PATTERN,
)
from src.core.config import settings
from src.core.logging import error_logger, log_event, request_logger
from src.db.database import (
    get_session_turns, get_sessions, get_share_token, get_shared_session, rename_session, share_session, stop_sharing,
    update_conversation_feedback,
)
from src.llm.llm_client import MODEL_BUSY, is_unavailable, setup_problem
from src.retrieval.scope import ScopeError, check_chosen
from src.memory.conversation import clear_session
from src.pipeline import rag

router = APIRouter()

# Route handlers are plain `def` on purpose: they call blocking code (Gemini, Chroma,
# SQLite, bcrypt), and FastAPI runs `def` handlers in a thread pool, so one slow
# request does not stall every other request.

def _check_scope(user_id: int, chat_request: ChatRequest) -> None:
    """400 when the request chose documents to search in and none of them can be searched."""
    try:
        check_chosen(user_id, chat_request.document_ids)
    except ScopeError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
    _check_scope(user_id, chat_request)

    try:
        result = rag.answer(user_id, chat_request.question, session_id=chat_request.session_id, mode=mode,
                            document_ids=chat_request.document_ids)
    except Exception as e:
        if is_unavailable(e):  # over quota or unavailable, after the retries (B10)
            log_event(error_logger, "chat_model_unavailable", level=logging.WARNING, user_id=user_id, mode=mode)
            raise HTTPException(status_code=503, detail=MODEL_BUSY)
        problem = setup_problem(e)
        if problem:  # something the owner must fix on this computer, such as Ollama not running
            log_event(error_logger, "chat_model_setup", level=logging.ERROR, user_id=user_id, mode=mode, cause=repr(e))
            raise HTTPException(status_code=503, detail=problem)
        raise server_error(request, "chat_failed", user_id=user_id, mode=mode, session=chat_request.session_id)

    # The question's length is logged, never its text (S10); with what each stage cost (Sprint 8)
    log_event(request_logger, "chat_ok", user_id=user_id, mode=mode, session=chat_request.session_id,
              question_chars=len(chat_request.question), confidence=result.get("confidence"),
              sources=len(result.get("sources", [])), seconds=round(time.time() - start_time, 2),
              usage=result.get("usage"))

    return ChatResponse(
        answer=result["answer"],
        sources=result["sources"],
        confidence=result.get("confidence", 0.0),
        session_id=chat_request.session_id,
        tool_used=result.get("tool_used"),
        steps=result.get("steps"),
        turn_id=result.get("turn_id"),
        usage=result.get("usage"),
        scope=result.get("scope"),
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
    _check_scope(user_id, chat_request)  # before the stream starts: once it has, it cannot answer 400
    log_event(request_logger, "stream_request", user_id=user_id, mode=mode, session=session,
              question_chars=len(chat_request.question), chosen=len(chat_request.document_ids or []))
    ref = reference(request)

    # A plain generator: Starlette runs it in a worker thread, so a slow model
    # call does not block the event loop and tokens are sent as they arrive.
    def generate_stream():
        try:
            for event in rag.events(user_id, chat_request.question, session_id=session, mode=mode,
                                    document_ids=chat_request.document_ids):
                if event["type"] == "done":
                    log_event(request_logger, "stream_ok", user_id=user_id, mode=mode, session=session,
                              confidence=event.get("confidence"), sources=len(event["sources"]), usage=event.get("usage"))
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            problem = setup_problem(e)
            if is_unavailable(e):  # over quota or unavailable, after the retries (B10)
                log_event(error_logger, "stream_model_unavailable", level=logging.WARNING, user_id=user_id, mode=mode)
                message = MODEL_BUSY
            elif problem:  # something the owner must fix on this computer, such as Ollama not running
                log_event(error_logger, "stream_model_setup", level=logging.ERROR, user_id=user_id, mode=mode, cause=repr(e))
                message = problem
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


# A session id in a path is held to the same rules as one in a request body
SessionPath = Path(max_length=100, pattern=SESSION_ID_PATTERN)

NO_SUCH_CONVERSATION = "No such conversation."


@router.get("/api/v1/sessions/{session_id}/messages", response_model=SessionMessages, tags=["Session"])
def session_messages(session_id: str = SessionPath, user_id: int = Depends(get_current_user)):
    """Every turn of one of the user's conversations, oldest first, with the sources and tool
    shown with each answer. Empty for a session with no turns, or one that is not the user's."""
    turns = [{**t, "turn_id": t["id"]} for t in get_session_turns(user_id, session_id)]
    return {"session_id": session_id, "turns": turns}


# ── Renaming and deleting a conversation (Sprint 8, item 3) ──────────────────

@router.patch("/api/v1/sessions/{session_id}", response_model=SessionTitle, tags=["Session"])
def rename_conversation(rename: SessionRename, session_id: str = SessionPath, user_id: int = Depends(get_current_user)):
    """Give one of the user's conversations a name, shown in place of its first question.
    404 for a conversation that is not the user's, or has no turns yet."""
    if not rename_session(user_id, session_id, rename.title):
        raise HTTPException(status_code=404, detail=NO_SUCH_CONVERSATION)
    log_event(request_logger, "session_renamed", user_id=user_id, session=session_id, title_chars=len(rename.title))
    return {"session_id": session_id, "title": rename.title}


@router.delete("/api/v1/sessions/{session_id}", response_model=SessionCleared, tags=["Session"])
def delete_conversation(session_id: str = SessionPath, user_id: int = Depends(get_current_user)):
    """Delete one of the user's conversations: every turn, its feedback and its name. 404 for a
    conversation that is not the user's."""
    deleted = clear_session(user_id, session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=NO_SUCH_CONVERSATION)
    log_event(request_logger, "session_deleted", user_id=user_id, session=session_id, turns=deleted)
    return {"message": "Conversation deleted", "session_id": session_id}


# ── Sharing a conversation: a link anyone can read it by ─────────────────────
# The owner makes the link and can withdraw it. Whoever has it can read that one conversation,
# with the passages it cites, and nothing else: no library, no other conversation, no asking.
# The token is the only secret, so it is never written to a log.

@router.post("/api/v1/sessions/{session_id}/share", response_model=ShareState, tags=["Session"])
def share_conversation(session_id: str = SessionPath, user_id: int = Depends(get_current_user)):
    """Share one of the user's conversations. Sharing it again gives the same link. 404 for a
    conversation that is not the user's, or has no turns yet."""
    token = share_session(user_id, session_id)
    if token is None:
        raise HTTPException(status_code=404, detail=NO_SUCH_CONVERSATION)
    log_event(request_logger, "session_shared", user_id=user_id, session=session_id)
    return {"session_id": session_id, "token": token}


@router.get("/api/v1/sessions/{session_id}/share", response_model=ShareState, tags=["Session"])
def sharing_of_conversation(session_id: str = SessionPath, user_id: int = Depends(get_current_user)):
    """Whether one of the user's conversations is shared, and by which link."""
    return {"session_id": session_id, "token": get_share_token(user_id, session_id)}


@router.delete("/api/v1/sessions/{session_id}/share", response_model=ShareState, tags=["Session"])
def stop_sharing_conversation(session_id: str = SessionPath, user_id: int = Depends(get_current_user)):
    """Withdraw the link. It stops working at once; sharing again makes a new one."""
    if stop_sharing(user_id, session_id):
        log_event(request_logger, "session_unshared", user_id=user_id, session=session_id)
    return {"session_id": session_id, "token": None}


SHARE_TOKEN_PATTERN = r"^[A-Za-z0-9_-]+$"
NOT_SHARED = "This conversation is not shared, or its link was withdrawn."


@router.get("/api/v1/shared/{token}", response_model=SharedConversation, tags=["Session"])
def shared_conversation(token: str = Path(min_length=20, max_length=64, pattern=SHARE_TOKEN_PATTERN)):
    """A shared conversation, for anyone who has its link: no sign-in. 404 for a link that was
    never made or has been withdrawn."""
    shared = get_shared_session(token)
    turns = get_session_turns(shared["user_id"], shared["session_id"]) if shared else []
    if not turns:
        raise HTTPException(status_code=404, detail=NOT_SHARED)
    log_event(request_logger, "shared_session_read", user_id=shared["user_id"], session=shared["session_id"])
    return {"title": shared["title"], "turns": turns}
