import logging
import re
import time
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.routing import Match
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.metrics import (
    HTTP_REQUEST_DURATION,
    HTTP_REQUESTS,
    HTTP_REQUESTS_IN_PROGRESS,
    method_label,
)
from app.core.request_context import reset_request_id, set_request_id

access_logger = logging.getLogger("app.access")

# Accept a caller's request ID only if it is plain and short. Anything else
# (for example one containing newlines) could be used to forge log lines.
SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9-]{8,64}")

# Health checks run every few seconds, so keep them out of normal logs.
QUIET_PATHS = {"/health/live", "/health/ready", "/metrics"}

# Prometheus scrapes /metrics constantly. Leaving it out of the numbers stops
# the monitoring from measuring itself.
METRICS_PATH = "/metrics"


def route_template(scope: Scope) -> str:
    """Return the route's path template, such as /incidents/{incident_id}.

    FastAPI's own routes record themselves in the scope. Built-in pages such
    as /docs do not, so for those we ask the router which route matches.
    """
    route = scope.get("route")

    if route is not None:
        return route.path

    for candidate in getattr(scope.get("app"), "routes", []):
        match, _ = candidate.matches(scope)

        if match == Match.FULL:
            return candidate.path

    return "unmatched"


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
        measured = scope["path"] != METRICS_PATH

        if measured:
            HTTP_REQUESTS_IN_PROGRESS.inc()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code

            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id

            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            elapsed = time.perf_counter() - started
            duration_ms = round(elapsed * 1000, 2)

            # Log the route template (/incidents/{incident_id}), never the real
            # URL: it keeps IDs and query strings out of the logs.
            route = route_template(scope)
            client = scope.get("client")

            if measured:
                method = method_label(scope["method"])
                HTTP_REQUESTS.labels(method, route, str(status_code)).inc()
                HTTP_REQUEST_DURATION.labels(method, route).observe(elapsed)
                HTTP_REQUESTS_IN_PROGRESS.dec()

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
