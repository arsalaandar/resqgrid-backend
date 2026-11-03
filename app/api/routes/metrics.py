import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.core.config import settings
from app.core.metrics import update_threadpool_metrics

router = APIRouter(include_in_schema=False)


def require_metrics_token(authorization: str | None = Header(default=None)) -> None:
    """Allow the request only if it carries the metrics token.

    With no METRICS_TOKEN configured (local development), /metrics is open.
    """
    token = settings.METRICS_TOKEN

    if not token:
        return

    expected = f"Bearer {token}".encode()
    supplied = (authorization or "").encode()

    # compare_digest takes the same time however many characters match, so the
    # response time cannot be used to guess the token one character at a time.
    if not secrets.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized.",
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.get("/metrics", dependencies=[Depends(require_metrics_token)])
async def metrics() -> Response:
    # Async so it runs inside the event loop, where the thread pool can be read.
    update_threadpool_metrics()

    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
