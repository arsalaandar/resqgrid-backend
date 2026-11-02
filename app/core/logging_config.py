import json
import logging
import logging.config
from datetime import UTC, datetime

from app.core.config import settings
from app.core.request_context import get_request_id

# Extra fields a log call may attach with logger.info(..., extra={...}).
# Only these are copied into the JSON, so nothing sensitive slips in by accident.
_EXTRA_FIELDS = ("method", "route", "status", "duration_ms", "client_ip")


class RequestIdFilter(logging.Filter):
    """Stamps every log record with the current request's ID."""

    def filter(self, record: logging.LogRecord) -> bool:
        # A log call may pass its own request_id (the error handler does,
        # because the context variable is already cleared by then).
        explicit = getattr(record, "request_id", None)
        record.request_id = explicit or get_request_id() or "-"
        return True


class JsonFormatter(logging.Formatter):
    """Renders each log record as one line of JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }

        for field in _EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


class _DropUvicornTraceback(logging.Filter):
    """The app logs unhandled errors itself, so hide uvicorn's duplicate."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.getMessage() != "Exception in ASGI application"


def configure_logging() -> None:
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {
                "request_id": {"()": RequestIdFilter},
                "drop_uvicorn_traceback": {"()": _DropUvicornTraceback},
            },
            "formatters": {
                "json": {"()": JsonFormatter},
                "text": {
                    "format": (
                        "%(asctime)s %(levelname)s [%(request_id)s] "
                        "%(name)s: %(message)s"
                    )
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": settings.LOG_FORMAT,
                    "filters": ["request_id"],
                }
            },
            "root": {"level": settings.LOG_LEVEL, "handlers": ["console"]},
            "loggers": {
                # Send uvicorn's own messages through our handler and formatter.
                "uvicorn": {"handlers": [], "propagate": True},
                "uvicorn.error": {
                    "handlers": [],
                    "propagate": True,
                    "filters": ["drop_uvicorn_traceback"],
                },
                # We write our own access log, so silence uvicorn's.
                "uvicorn.access": {"handlers": [], "propagate": False},
            },
        }
    )
