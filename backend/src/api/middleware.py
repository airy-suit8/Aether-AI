"""
api/middleware.py — what every response carries (S10): a request id and the security headers.

Every request gets a short random id. It is sent back as X-Request-ID, written on every log line
made while serving it (core/logging.request_id), and quoted in a server error's message, so a
person who reports "reference 3f2a9c…" can be matched to the log without the client ever seeing
the error itself.
"""

import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.core.logging import request_id

# The app loads only its own files: scripts, styles, fonts and requests stay on this origin.
# Images may also be data: URIs (the background grain is one), never a remote URL, so a model
# answer cannot leak text through an image address (S3). No page may frame the app.
CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "img-src 'self' data:",
    "font-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}

# FastAPI's API pages load their script from a CDN; they exist only in development (core/config.py)
PAGES_WITHOUT_CSP = ("/docs", "/redoc")


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


class RequestMiddleware:
    """Gives each HTTP request an id and adds X-Request-ID and the security headers to its response."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        rid = new_request_id()
        scope.setdefault("state", {})["request_id"] = rid
        token = request_id.set(rid)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = rid
                for name, value in SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
                if not scope["path"].startswith(PAGES_WITHOUT_CSP):
                    headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        finally:
            request_id.reset(token)
