"""api/routes_health.py — the health check."""

from datetime import datetime

from fastapi import APIRouter, Request

from src.core.config import APP_VERSION
from src.db.database import get_conversation_stats, get_document_stats

router = APIRouter()


@router.get("/api/v1/health", tags=["System"])
def health_check(request: Request):
    """Health check endpoint for monitoring and load balancers."""
    uptime = (datetime.now() - request.app.state.started_at).total_seconds()
    doc_stats = get_document_stats()
    conv_stats = get_conversation_stats()
    return {
        "status": "ok",
        "version": APP_VERSION,
        "uptime_seconds": round(uptime, 1),
        "documents": doc_stats,
        "conversations": conv_stats,
    }
