"""
core/security.py — password hashing and signed login tokens (JWT).

The secret is read from settings when a token is signed or checked, so importing this module
needs no secret; main.create_app() refuses to build the app without one.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt

from src.core.config import settings

ALGORITHM: str = "HS256"


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


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a signed JWT with an expiration claim."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.require_jwt_secret(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Return the token's claims. Raises jwt.ExpiredSignatureError or jwt.PyJWTError."""
    return jwt.decode(token, settings.require_jwt_secret(), algorithms=[ALGORITHM])
