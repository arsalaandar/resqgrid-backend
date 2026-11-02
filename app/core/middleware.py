import logging
import re
import time
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.request_context import reset_request_id, set_request_id

access_logger = logging.getLogger("app.access")

# Accept a caller's request ID only if it is plain and short. Anything else
# (for example one containing newlines) could be used to forge log lines.
SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9-]{8,64}")

# Health checks run every few seconds, so keep them out of normal logs.
QUIET_PATHS = {"/health/live", "/health/ready"}


class RequestContextMiddleware:
    """Gives each request an ID, times it, and writes one access-log line."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get("x-request-id", "")
        request_id = (
            incoming if SAFE_REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex
        )

        # Make the ID available to exception handlers through request.state.
        scope.setdefault("state", {})["request_id"] = request_id
        token = set_request_id(request_id)

        started = time.perf_counter()
        status_code = 500  # Stays 500 if the app raises before responding.

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code

            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id

            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)

            # Log the route template (/incidents/{incident_id}), never the real
            # URL: it keeps IDs and query strings out of the logs.
            route = getattr(scope.get("route"), "path", None) or "unmatched"
            client = scope.get("client")

            level = logging.DEBUG if scope["path"] in QUIET_PATHS else logging.INFO
            access_logger.log(
                level,
                "request completed",
                extra={
                    "method": scope["method"],
                    "route": route,
                    "status": status_code,
                    "duration_ms": duration_ms,
                    "client_ip": client[0] if client else None,
                },
            )

            reset_request_id(token)
