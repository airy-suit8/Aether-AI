"""api/schemas.py — the request and response models of the HTTP API."""

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

# Session ids become cache keys, database values and log text: keep them short and plain
SessionId = Field(default="default", min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")


class ChatRequest(BaseModel):
    question: str
    session_id: str = SessionId
    use_agent: bool = False
    use_langchain: bool = False
    use_hybrid: bool = False

    def mode(self) -> str:
        """The pipeline mode the flags select; the agent wins, then LangChain, then hybrid."""
        if self.use_agent:
            return "agent"
        if self.use_langchain:
            return "langchain"
        return "hybrid" if self.use_hybrid else "default"

class ChatResponse(BaseModel):
    answer: str
    sources: list
    confidence: float = 0.0
    session_id: str = "default"
    tool_used: Optional[str] = None  # agent mode: which tools answered

class FeedbackRequest(BaseModel):
    session_id: str = SessionId
    feedback: Literal[-1, 0, 1]  # 1 for up, -1 for down, 0 to clear

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
