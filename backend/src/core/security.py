"""
core/security.py — password hashing and signed login tokens (JWT).

Two kinds of token (S7), told apart by their "type" claim so neither can stand in for the other:
  access   sent with every API request; lasts settings.access_token_minutes
  refresh  kept in an httpOnly cookie and used only to get a new access token; lasts
           settings.refresh_token_days
Both name the user ("sub") and the user's tenant id ("tid"), so a token stops working when its
user is gone, including after a database reset that gave the same number to someone else.

The secret is read from settings when a token is signed or checked, so importing this module
needs no secret; main.create_app() refuses to build the app without one.
"""

import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Optional

import bcrypt
import jwt

from src.core.config import settings

ALGORITHM: str = "HS256"
ACCESS, REFRESH = "access", "refresh"

# bcrypt reads only the first 72 bytes of a password, and bcrypt 5 refuses longer ones
PASSWORD_MAX_BYTES = 72


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    """Hash a password using direct bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


@lru_cache(maxsize=1)
def unknown_user_hash() -> str:
    """A hash to check a password against when no user has the name given, so that a login for
    an unknown name takes as long as one with a wrong password (S7). Made on first use."""
    return get_password_hash("no user has this password")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a signed JWT with an expiration claim. Its type is "access" unless data says otherwise."""
    to_encode = {"type": ACCESS, **data}
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=15))
    # A unique id, so two tokens made in the same second still differ
    to_encode.update({"exp": expire, "jti": uuid.uuid4().hex})
    return jwt.encode(to_encode, settings.require_jwt_secret(), algorithm=ALGORITHM)


def tokens_for(user: dict) -> tuple:
    """A new (access token, refresh token) pair for a user row."""
    claims = {"sub": str(user["id"]), "tid": user["tenant_id"]}
    return (
        create_access_token({**claims, "type": ACCESS}, timedelta(minutes=settings.access_token_minutes)),
        create_access_token({**claims, "type": REFRESH}, timedelta(days=settings.refresh_token_days)),
    )


def decode_access_token(token: str, kind: str = ACCESS) -> dict:
    """Return the token's claims. Raises jwt.ExpiredSignatureError, or jwt.PyJWTError for any
    other fault, including a token of the other kind."""
    claims = jwt.decode(token, settings.require_jwt_secret(), algorithms=[ALGORITHM])
    if claims.get("type") != kind:
        raise jwt.InvalidTokenError(f"not an {kind} token")
    return claims
