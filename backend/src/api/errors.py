"""
api/errors.py — server errors as the client sees them (S10): a general message and a reference.

The exception itself, its traceback and the request's fields go to errors.log under the request
id; the client gets only "something went wrong" and that id, never exception text, which can
name a server path, a library or a piece of a document.
"""

import logging
import math
import time
from typing import Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from src.core.logging import error_logger, log_event


def reference(request: Request) -> str:
    """The request's id (X-Request-ID), as quoted to the client."""
    return getattr(request.state, "request_id", None) or "none"


def server_error(request: Request, event: str, **fields) -> HTTPException:
    """Log the exception being handled, then return the 500 to raise in its place."""
    log_event(error_logger, event, level=logging.ERROR, exc_info=True, **fields)
    return HTTPException(
        status_code=500,
        detail=f"Something went wrong on the server. Please try again. Reference: {reference(request)}",
    )


async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    """For an exception no route caught: the same general message, as JSON, instead of a bare text 500."""
    rid = reference(request)
    # Called outside the request middleware, so the request id is given explicitly
    log_event(error_logger, "unhandled_error", level=logging.ERROR, exc_info=(type(exc), exc, exc.__traceback__),
              request_id=rid, method=request.method, path=request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": f"Something went wrong on the server. Please try again. Reference: {rid}"},
        headers={"X-Request-ID": rid},
    )


def _seconds_to_wait(request: Request) -> Optional[int]:
    """How long until the limit just hit lets a request through again, or None if unknown."""
    hit = getattr(request.state, "view_rate_limit", None)  # (limit, its key), set by the limiter
    if not hit:
        return None
    try:
        reset_at, _ = request.app.state.limiter.limiter.get_window_stats(hit[0], *hit[1])
    except Exception:
        return None
    return max(1, math.ceil(reset_at - time.time()))


def rate_limited(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """A 429 in the shape of every other error (N1): a detail written for the person, and how
    many seconds to wait in Retry-After, which the web app turns into its message. Both the
    routes' own limits and the default limit on every route (S8) answer through this."""
    wait = _seconds_to_wait(request)
    if wait is None:
        return JSONResponse(status_code=429, content={"detail": "Too many requests. Please wait a moment and try again."})
    return JSONResponse(
        status_code=429,
        content={"detail": f"Too many requests. Please wait {wait} second{'s' if wait != 1 else ''} and try again."},
        headers={"Retry-After": str(wait)},
    )
