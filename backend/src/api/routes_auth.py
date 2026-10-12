"""api/routes_auth.py — register and log in."""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm

from src.api.deps import limiter
from src.api.schemas import Token, UserRegister
from src.core.config import settings
from src.core.security import create_access_token, get_password_hash, verify_password
from src.db.database import create_user, get_user_by_username

router = APIRouter()

# Route handlers are plain `def` on purpose: they call blocking code (Gemini, Chroma,
# SQLite, bcrypt), and FastAPI runs `def` handlers in a thread pool, so one slow
# request does not stall every other request.

@router.post("/api/v1/auth/register", tags=["Auth"])
@limiter.limit(settings.rate_limit_register)
def register(user: UserRegister, request: Request):
    if get_user_by_username(user.username):
        raise HTTPException(status_code=400, detail="Username already registered")
    hashed_password = get_password_hash(user.password)
    user_id = create_user(user.username, hashed_password)
    return {"message": "User registered successfully", "user_id": user_id}

@router.post("/api/v1/auth/login", response_model=Token, tags=["Auth"])
@limiter.limit(settings.rate_limit_login)
def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):
    user = get_user_by_username(form_data.username)
    if not user or not verify_password(form_data.password, user["password_hash"]):
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=settings.access_token_minutes)
    access_token = create_access_token(
        data={"sub": str(user["id"])}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}
