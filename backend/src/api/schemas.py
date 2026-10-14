"""api/schemas.py — the request and response models of the HTTP API.

Every reply has a model, so the OpenAPI schema describes it and the web app's types are generated
from that schema (frontend/src/services/api-schema.ts). The streamed events are written as JSON
by the pipeline; their models here describe them, and a test checks each event against them.
"""

import re
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.core.security import PASSWORD_MAX_BYTES

# Session ids become cache keys, database values and log text: keep them short and plain
SESSION_ID_PATTERN = r"^[A-Za-z0-9_.:-]+$"
SessionId = Field(default="default", min_length=1, max_length=100, pattern=SESSION_ID_PATTERN)


class ChatRequest(BaseModel):
    # Unknown fields are refused, so a client still sending the old use_agent / use_langchain /
    # use_hybrid flags gets a 422 instead of a silent default-mode answer.
    model_config = ConfigDict(extra="forbid")

    question: str
    session_id: str = SessionId
    mode: Literal["default", "hybrid", "agent", "langchain"] = "default"
    # Search only these documents (ids from GET /documents/detailed): the composer's "Search in".
    # Absent: every document, unless the question names some (retrieval/scope.py).
    document_ids: Optional[list[int]] = Field(default=None, min_length=1, max_length=100)


class Source(BaseModel):
    """A passage an answer came from, as it is shown beside the answer."""
    source: str             # the file name
    page: Union[int, str]   # numbered from 1; "?" when the passage has no page
    snippet: str            # the start of the passage
    score: float            # cosine similarity to the question, 0 to 1
    # With AETHER_ANSWER_FROM=chunks: the [n] the answer cites this passage by. Absent otherwise.
    number: Optional[int] = Field(default=None, exclude_if=lambda n: n is None)
    # Which document it is, of what kind (pdf, docx, text, csv, xlsx, xls), and where the passage
    # sits in it: passage 3 of passages 74. Absent for a passage stored before these were kept.
    document_id: Optional[int] = Field(default=None, exclude_if=lambda n: n is None)
    kind: Optional[str] = Field(default=None, exclude_if=lambda n: n is None)
    passage: Optional[int] = Field(default=None, exclude_if=lambda n: n is None)
    passages: Optional[int] = Field(default=None, exclude_if=lambda n: n is None)


class ScopeDocument(BaseModel):
    """A document an answer searched."""
    document_id: int
    name: str       # its title, when its first passage has one; else its file name
    filename: str


class Scope(BaseModel):
    """The documents an answer searched, and how they were picked: "all" of them, "chosen" in the
    request, "named" in the question, or the "kind" of file the question named."""
    how: Literal["all", "chosen", "named", "kind"]
    documents: list[ScopeDocument]


class UsageStage(BaseModel):
    """One stage of an answer: rewrite, retrieve, summarize, answer; or agent, document_search."""
    name: str
    seconds: float
    input_tokens: int   # as the model's API reported them; 0 for a stage with no model call
    output_tokens: int


class AgentStep(BaseModel):
    """One tool call of an agent answer, in the order they ran (Sprint 8, item 2)."""
    tool: str    # document_search, calculator or datetime, as in tool_used
    input: str   # what the tool was asked
    output: str  # the start of what it returned, on one line


class Usage(BaseModel):
    """What an answer cost (Sprint 8, item 1). Tokens are counted, never priced."""
    seconds: float      # from the question to the answer
    input_tokens: int
    output_tokens: int
    stages: list[UsageStage]  # in the order they ran


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]
    # How close the retrieved passages were, 0 to 1. null when the agent answered without
    # searching the documents: there is nothing to be confident about (R11).
    confidence: Optional[float] = 0.0
    session_id: str = "default"
    tool_used: Optional[str] = None  # agent mode: which tools answered
    steps: Optional[list[AgentStep]] = None  # agent mode: each tool call, in order; null in the other modes
    turn_id: Optional[int] = None    # the saved turn, for POST /feedback; null when none was saved (a refusal)
    usage: Optional[Usage] = None
    scope: Optional[Scope] = None    # what was searched; null when there was nothing to search


# ── The events of POST /chat/stream, one per `data:` line ─────────────────────

class TokenEvent(BaseModel):
    """A piece of the answer, in order."""
    type: Literal["token"]
    content: str


class DoneEvent(BaseModel):
    """The last event of an answer."""
    type: Literal["done"]
    sources: list[Source]
    confidence: Optional[float]  # as in ChatResponse
    turn_id: Optional[int]       # as in ChatResponse
    tool_used: Optional[str] = None  # agent mode only: which tools answered
    steps: Optional[list[AgentStep]] = None  # as in ChatResponse
    usage: Optional[Usage] = None    # as in ChatResponse
    scope: Optional[Scope] = None    # as in ChatResponse


class ErrorEvent(BaseModel):
    """The last event of an answer that could not be finished. Nothing of it was saved."""
    type: Literal["error"]
    message: str    # written for the person who asked
    reference: str  # the request id, as in a server error's message


StreamEvent = Annotated[Union[TokenEvent, DoneEvent, ErrorEvent], Field(discriminator="type")]


class Message(BaseModel):
    """A reply that only says what happened."""
    message: str


class Health(BaseModel):
    status: Literal["ok"]


class SessionCleared(BaseModel):
    message: str
    session_id: str


class FeedbackRequest(BaseModel):
    # Unknown fields are refused, so a client still sending the old session_id gets a 422 (F10)
    model_config = ConfigDict(extra="forbid")

    turn_id: int                 # from the answer: ChatResponse.turn_id, or the stream's done event
    feedback: Literal[-1, 0, 1]  # 1 for up, -1 for down, 0 to clear

class UploadResponse(BaseModel):
    """An accepted upload. It is read in the background: GET /documents/{document_id} says when
    it is ready, or why it failed (R12)."""
    document_id: int
    filename: str
    status: Literal["processing"] = "processing"
    replaces: bool = False  # an earlier file of the same name is replaced once this one is read
    message: str


class DocumentStatus(BaseModel):
    """One document in a user's library, and how reading it went."""
    id: int
    filename: str
    status: Literal["processing", "ready", "failed"]
    error: Optional[str] = None  # why it failed, written for the person who uploaded it
    pages: int
    chunks: int
    size_bytes: int
    uploaded_at: str


class DocumentRecord(DocumentStatus):
    """A document as the detailed list gives it: its status, and the hash that spots a duplicate upload."""
    file_hash: Optional[str] = None
    # The first line of its first passage that reads like a title ("Classification of Maternal
    # Health Risks using Boosting Technique"); null while it is read, or when it has none
    title: Optional[str] = None
    kind: Optional[str] = None  # pdf, docx, text, csv, xlsx or xls; null while it is read


class DocumentList(BaseModel):
    documents: list[DocumentRecord]  # newest first
    count: int


class DocumentNames(BaseModel):
    documents: list[str]  # the names of the documents ready to be searched, sorted
    count: int


class DocumentDeleted(BaseModel):
    message: str
    filename: str
    deleted: int  # chunks removed from the vector store


class DocumentsCleared(BaseModel):
    message: str
    status: Literal["cleared"]
    deleted: int  # chunks removed from the vector store

# Sign-up rules (S7). The web app's sign-up form mirrors them (LandingPage.tsx).
USERNAME_PATTERN = re.compile(r"[A-Za-z0-9_-]{3,50}")
PASSWORD_MIN_CHARS = 8


class UserRegister(BaseModel):
    username: str
    password: str
    # Needed when the server sets AETHER_INVITE_CODE; ignored otherwise
    invite_code: str = Field(default="", max_length=200)

    @field_validator('username')
    @classmethod
    def username_valid(cls, v: str) -> str:
        # Trimmed here and at login alike, so "  name  " signs in as the name it registered
        v = v.strip()
        if len(v) < 3:
            raise ValueError('Username must be at least 3 characters')
        if len(v) > 50:
            raise ValueError('Username must be at most 50 characters')
        # ASCII only, so no two names can look alike; case is ignored when names are compared
        if not USERNAME_PATTERN.fullmatch(v):
            raise ValueError('Username may only contain the letters A to Z, digits, hyphens and underscores')
        return v

    @field_validator('password')
    @classmethod
    def password_valid(cls, v: str) -> str:
        if len(v) < PASSWORD_MIN_CHARS:
            raise ValueError(f'Password must be at least {PASSWORD_MIN_CHARS} characters')
        if len(v.encode("utf-8")) > PASSWORD_MAX_BYTES:
            raise ValueError(f'Password must be at most {PASSWORD_MAX_BYTES} bytes (72 letters, fewer with accents or symbols)')
        return v

class Token(BaseModel):
    access_token: str
    token_type: str
    expires_in: int  # seconds until the access token expires; renew it at /auth/refresh


class Me(BaseModel):
    """The signed-in user, for a page that was reloaded and knows only its token."""
    username: str
    created_at: str


class SessionSummary(BaseModel):
    session_id: str
    title: str      # the conversation's first question
    turns: int
    started_at: str
    updated_at: str


class SessionList(BaseModel):
    sessions: list[SessionSummary]  # most recently used first


SESSION_TITLE_MAX_CHARS = 200


class SessionRename(BaseModel):
    """A new name for a conversation (Sprint 8, item 3)."""
    model_config = ConfigDict(extra="forbid")

    title: str = Field(max_length=SESSION_TITLE_MAX_CHARS)

    @field_validator('title')
    @classmethod
    def title_not_blank(cls, v: str) -> str:
        v = " ".join(v.split())  # one line, as the rail shows it
        if not v:
            raise ValueError('A conversation needs a name')
        return v


class SessionTitle(BaseModel):
    session_id: str
    title: str


class Turn(BaseModel):
    """One question and its answer, as they were shown."""
    turn_id: int
    question: str
    answer: str
    confidence: Optional[float] = None
    mode: str
    sources: list[Source]
    tool_used: Optional[str] = None
    feedback: int
    created_at: str


class SessionMessages(BaseModel):
    session_id: str
    turns: list[Turn]  # oldest first


# ── Sharing a conversation ────────────────────────────────────────────────────

class ShareState(BaseModel):
    """Whether one of the user's conversations is shared. The page that shows it is /shared/{token}."""
    session_id: str
    token: Optional[str] = None  # null when the conversation is not shared


class SharedTurn(BaseModel):
    """One question and its answer in a shared conversation: what its owner saw, without the
    turn's id or the owner's rating."""
    question: str
    answer: str
    confidence: Optional[float] = None
    mode: str
    sources: list[Source]
    tool_used: Optional[str] = None
    created_at: str


class SharedConversation(BaseModel):
    """A conversation as anyone with its link sees it. It says nothing about whose it is."""
    title: str
    turns: list[SharedTurn]  # oldest first
