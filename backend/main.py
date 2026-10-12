"""
main.py — the entry point: builds the Aether AI app (python -m uvicorn main:app, from backend/).

create_app() checks the JWT secret, adds CORS and the rate limiter, includes the API routers
from src/api/ and serves the built React app at /. The lifespan hook sets up the log files
and the database tables when the server starts. Nothing is opened at import: the vector store
opens on first use (it needs the Gemini key, so a server without one still starts).

Endpoints (all under /api/v1):
  POST /auth/register, /auth/login    routes_auth
  GET  /health                        routes_health
  POST /upload, GET /documents, GET /documents/detailed, DELETE /documents   routes_documents
  POST /chat, /chat/stream, /feedback, /session/clear                        routes_chat
  GET  /                              the built React app (frontend/dist), mounted after the API
"""

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from src.api import routes_auth, routes_chat, routes_documents, routes_health
from src.api.deps import limiter
from src.core.config import APP_VERSION, settings
from src.core.logging import setup_logging
from src.db.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open what the app writes to: the log files and the database tables."""
    setup_logging(settings.log_dir)
    init_db()
    yield


def create_app() -> FastAPI:
    """Build the app. Refuses to build without a JWT secret."""
    settings.require_jwt_secret()

    app = FastAPI(
        title="Aether AI — Knowledge Assistant API",
        description="A Retrieval-Augmented Generation chatbot powered by Google Gemini",
        version=APP_VERSION,
        lifespan=lifespan,
    )
    app.state.limiter = limiter
    app.state.started_at = datetime.now()
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for module in (routes_auth, routes_health, routes_documents, routes_chat):
        app.include_router(module.router)
    mount_frontend(app, FRONTEND_DIST)
    return app


# ── Serve the React app ───────────────────────────────────────────────────────
# Mounted last, so every /api/v1 route above is matched first.

FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"

_FRONTEND_NOT_BUILT = """<!doctype html>
<html><head><meta charset="utf-8"><title>Aether AI</title></head>
<body style="font-family: sans-serif; max-width: 40em; margin: 4em auto; line-height: 1.5">
<h1>Aether AI backend is running</h1>
<p>The web app has not been built, so there is nothing to show here yet. Either:</p>
<ul>
<li>run the development server: <code>cd frontend</code>, <code>npm run dev</code>, then open
<a href="http://localhost:5173">http://localhost:5173</a>; or</li>
<li>build it once: <code>cd frontend</code>, <code>npm ci</code>, <code>npm run build</code>,
then restart the backend and reload this page.</li>
</ul>
<p>The API is at <a href="/docs">/docs</a>.</p>
</body></html>"""


def mount_frontend(app: FastAPI, dist_dir: Path):
    """Serve the built React app at /, or a page explaining how to build it."""
    if (dist_dir / "index.html").is_file():
        app.mount("/", StaticFiles(directory=str(dist_dir), html=True), name="frontend")
    else:
        @app.get("/", include_in_schema=False)
        def frontend_not_built():
            return HTMLResponse(_FRONTEND_NOT_BUILT)



app = create_app()
