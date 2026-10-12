"""api/routes_health.py — the health check."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/api/v1/health", tags=["System"])
def health_check():
    """Health check for monitoring and load balancers. Status only: it is public, so it says
    nothing about the version, the uptime or anyone's documents (S10)."""
    return {"status": "ok"}
