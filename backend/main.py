"""
main.py — the entry point: builds the Aether AI app (python -m uvicorn main:app, from backend/).

create_app() checks the JWT secret, adds CORS and the rate limiter, includes the API routers
from src/api/ and serves the built React app at /. The lifespan hook sets up the log files
and the database tables when the server starts, files chunks stored before tenant ids under
their owner's tenant id, and marks uploads a restart cut short as failed. Nothing is opened at import, and a server without a Gemini key
still starts: only adding and searching chunks need it.

Endpoints (all under /api/v1):
  POST /auth/register, /auth/login    routes_auth
  GET  /health                        routes_health
  POST /upload, GET /documents, GET /documents/detailed, DELETE /documents   routes_documents
  POST /chat, /chat/stream, /feedback, /session/clear                        routes_chat
  GET  /                              the built React app (frontend/dist), mounted after the API
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIASGIMiddleware

from src.api import routes_auth, routes_chat, routes_documents, routes_health
from src.api.deps import limiter
from src.api.errors import unhandled_error
from src.api.middleware import RequestMiddleware
from src.core.config import APP_VERSION, settings
from src.core.logging import error_logger, log_event, setup_logging, upload_logger
from src.db.database import init_db
from src.pipeline.documents import migrate_chunks_to_tenants, recover_interrupted_uploads


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open what the app writes to: the log files and the database tables; re-key old chunks."""
    setup_logging(settings.log_dir)
    for note in settings.path_notes():
        error_logger.warning(note)
    init_db()
    moved = migrate_chunks_to_tenants()
    if moved["migrated"]:
        log_event(upload_logger, "chunks_filed_under_tenant_ids", chunks=moved["migrated"])
    if moved["unclaimed"]:
        error_logger.warning(
            f"{moved['unclaimed']} chunks in the vector store belong to no document in this database "
            "(left from an earlier database?). They are kept, and no user can search them.")
    interrupted = recover_interrupted_uploads()
    if interrupted:
        error_logger.warning(f"{interrupted} uploads were still being read when the server stopped; they are marked failed.")
    yield


def create_app() -> FastAPI:
    """Build the app. Refuses to build without a JWT secret."""
    settings.require_jwt_secret()
    development = settings.environment == "development"

    app = FastAPI(
        title="Aether AI — Knowledge Assistant API",
        description="A Retrieval-Augmented Generation chatbot powered by Google Gemini",
        version=APP_VERSION,
        lifespan=lifespan,
        # The API pages describe every route to anyone who asks: development only (S10)
        docs_url="/docs" if development else None,
        redoc_url="/redoc" if development else None,
        openapi_url="/openapi.json" if development else None,
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_exception_handler(Exception, unhandled_error)
    # The default rate limit for every route that has no limit of its own (S8)
    app.add_middleware(SlowAPIASGIMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    # Added last, so it is outermost: every response, CORS and rate-limit replies included
    app.add_middleware(RequestMiddleware)
    for module in (routes_auth, routes_health, routes_documents, routes_chat):
        app.include_router(module.router)
    mount_frontend(app, FRONTEND_DIST)
    return app


# ── Serve the React app ───────────────────────────────────────────────────────
# Mounted last, so every /api/v1 route above is matched first.

FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"

_FRONTEND_NOT_BUILT = """<!doctype html>
<html><head><meta charset="utf-8"><title>Aether AI</title></head>
<body>
<h1>Aether AI backend is running</h1>
<p>The web app has not been built, so there is nothing to show here yet. Either:</p>
<ul>
<li>run the development server: <code>cd frontend</code>, <code>npm run dev</code>, then open
<a href="http://localhost:5173">http://localhost:5173</a>; or</li>
<li>build it once: <code>cd frontend</code>, <code>npm ci</code>, <code>npm run build</code>,
then restart the backend and reload this page.</li>
</ul>
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
