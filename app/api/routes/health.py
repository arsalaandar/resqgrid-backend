import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.dependencies import get_db

router = APIRouter(prefix="/health", tags=["Health"])

logger = logging.getLogger(__name__)


@router.get("/live")
def live():
    """Liveness: the process is running and can answer a request.

    This must never touch the database. If it did, a database outage would
    make the platform think the app itself is broken and restart it, which
    does not fix the database and only makes the outage worse.
    """
    return {"status": "alive"}


@router.get("/ready")
def ready(db: Session = Depends(get_db)):
    """Readiness: this instance can do useful work right now.

    A failed readiness check tells the load balancer to stop sending traffic
    here, but it does not restart the app.
    """
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        # One short line, with no error details: this runs every few seconds
        # during an outage, and the response is visible to anyone who asks.
        logger.warning("Readiness check failed: %s", type(exc).__name__)
        return JSONResponse(status_code=503, content={"status": "unavailable"})

    return {"status": "ready"}
