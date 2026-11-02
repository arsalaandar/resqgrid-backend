from contextvars import ContextVar, Token

# Holds the ID of the request being handled. A ContextVar is isolated per
# request, so concurrent requests never see each other's value.
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    return _request_id.get()


def set_request_id(value: str) -> Token:
    return _request_id.set(value)


def reset_request_id(token: Token) -> None:
    _request_id.reset(token)
