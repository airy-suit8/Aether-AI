"""api/routes_auth.py — register, sign in, renew the access token, sign out (S7).

Signing in returns a short-lived access token and sets a refresh token in an httpOnly cookie,
which page scripts cannot read and the browser sends only to /api/v1/auth. /auth/refresh trades
it for a new access token, and a new refresh token, so a reloaded page stays signed in and a
week without use signs the user out; /auth/logout removes it.
"""

import hmac
import sqlite3

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import OAuth2PasswordRequestForm

from src.api.deps import get_current_user, limiter, user_for
from src.api.schemas import Me, Token, UserRegister
from src.core.config import settings
from src.core.logging import auth_logger, log_event
from src.core.security import REFRESH, decode_access_token, get_password_hash, tokens_for, unknown_user_hash, verify_password
from src.db.database import create_user, get_user_by_id, get_user_by_username

router = APIRouter()

REFRESH_COOKIE = "aether_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"
TAKEN = "Username already registered"

# Route handlers are plain `def` on purpose: they call blocking code (Gemini, Chroma,
# SQLite, bcrypt), and FastAPI runs `def` handlers in a thread pool, so one slow
# request does not stall every other request.

@router.post("/api/v1/auth/register", tags=["Auth"])
@limiter.limit(settings.rate_limit_register)
def register(user: UserRegister, request: Request):
    if settings.invite_code and not hmac.compare_digest(user.invite_code.encode(), settings.invite_code.encode()):
        log_event(auth_logger, "register_rejected", reason="invite_code")
        raise HTTPException(status_code=403, detail="Registration needs a valid invite code.")
    if get_user_by_username(user.username):
        log_event(auth_logger, "register_rejected", reason="taken")
        raise HTTPException(status_code=400, detail=TAKEN)
    hashed_password = get_password_hash(user.password)
    try:
        user_id = create_user(user.username, hashed_password)
    except sqlite3.IntegrityError:
        # Someone took the name between the check and the insert
        raise HTTPException(status_code=400, detail=TAKEN)
    log_event(auth_logger, "register_ok", user_id=user_id)
    # No user id in the reply: ids are sequential, and the client has no use for one
    return {"message": "User registered successfully"}


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE, refresh_token,
        max_age=settings.refresh_token_days * 24 * 3600,
        path=REFRESH_COOKIE_PATH, httponly=True, samesite="strict", secure=settings.cookie_secure,
    )


def _signed_in(response: Response, user: dict) -> Token:
    access_token, refresh_token = tokens_for(user)
    _set_refresh_cookie(response, refresh_token)
    return Token(access_token=access_token, token_type="bearer", expires_in=settings.access_token_minutes * 60)


@router.post("/api/v1/auth/login", response_model=Token, tags=["Auth"])
@limiter.limit(settings.rate_limit_login)
def login(request: Request, response: Response, form_data: OAuth2PasswordRequestForm = Depends()):
    username = form_data.username.strip()  # as register trims it
    user = get_user_by_username(username)
    # The password is checked even for a name no one has, so both failures take as long
    password_ok = verify_password(form_data.password, user["password_hash"] if user else unknown_user_hash())
    if not user or not password_ok:
        # The name tried is logged (JSON-escaped, cut to the longest valid length); never the password
        log_event(auth_logger, "login_failed", username=username[:50], known_user=bool(user))
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    log_event(auth_logger, "login_ok", user_id=user["id"])
    return _signed_in(response, user)


@router.post("/api/v1/auth/refresh", response_model=Token, tags=["Auth"])
def refresh(request: Request, response: Response):
    """A new access token for the refresh cookie set at sign-in. 401 when it is missing, expired,
    or names a user who is gone."""
    user = None
    token = request.cookies.get(REFRESH_COOKIE)
    if token:
        try:
            user = user_for(decode_access_token(token, kind=REFRESH))
        except jwt.PyJWTError:
            user = None
    if user is None:
        if token:
            log_event(auth_logger, "refresh_rejected")
        response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)
        raise HTTPException(status_code=401, detail="Not signed in.", headers={"WWW-Authenticate": "Bearer"})
    return _signed_in(response, user)


@router.post("/api/v1/auth/logout", tags=["Auth"])
def logout(request: Request, response: Response):
    """Remove the refresh cookie, so a reloaded page is signed out. The access token the client
    holds still works until it expires (at most settings.access_token_minutes)."""
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH, httponly=True, samesite="strict",
                           secure=settings.cookie_secure)
    log_event(auth_logger, "logout")
    return {"message": "Signed out"}


@router.get("/api/v1/auth/me", response_model=Me, tags=["Auth"])
def me(user_id: int = Depends(get_current_user)):
    """Who the access token belongs to (F8): a reloaded page knows its token but not the name."""
    return get_user_by_id(user_id)
