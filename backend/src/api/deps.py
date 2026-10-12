"""api/deps.py — request dependencies shared by the routers: the current user and the rate limiter."""

from typing import Any, Dict, Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.core.logging import auth_logger, log_event
from src.core.security import decode_access_token
from src.db.database import get_user_by_id

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login")

# Rate limiter, keyed by client address; the limits are in settings (rate_limit_*)
limiter = Limiter(key_func=get_remote_address)


def user_for(claims: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The user a token's claims name, or None when there is no such user any more, or the user
    with that id is someone else (another tenant id: the database was reset)."""
    try:
        user = get_user_by_id(int(claims.get("sub")))
    except (TypeError, ValueError):
        return None
    if user is None or user["tenant_id"] != claims.get("tid"):
        return None
    return user


def get_current_user(token: str = Depends(oauth2_scheme)) -> int:
    """FastAPI dependency: the id of the user the access token names, or a 401.

    A plain def: it reads the database, so FastAPI runs it in the thread pool.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        claims = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError:
        raise credentials_exception
    user = user_for(claims)
    if user is None:
        # A correctly signed token for a user who is gone: worth knowing about (S7)
        log_event(auth_logger, "token_rejected", reason="no_such_user", user_id=claims.get("sub"))
        raise credentials_exception
    return user["id"]
