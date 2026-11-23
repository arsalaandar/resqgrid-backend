import asyncio

import pytest
from pydantic import ValidationError
from starlette.responses import JSONResponse

from app.core.concurrency import ConcurrencyLimitMiddleware
from app.core.config import Settings
from app.core.metrics import HTTP_REQUESTS_SHED, HTTP_REQUESTS_WAITING


class Gate:
    """An inner app that holds each request open until the test opens the gate."""

    def __init__(self) -> None:
        self.open = asyncio.Event()
        self.started = 0
        self.fail_next = False

    async def __call__(self, scope, receive, send):
        self.started += 1

        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("boom")

        await self.open.wait()
        await JSONResponse({"ok": True})(scope, receive, send)


async def call(app, path="/work"):
    """Send one request through the app and return (status, headers)."""
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "path": path,
        "method": "GET",
        "headers": [],
        "query_string": b"",
        "client": ("test", 1),
    }
    await app(scope, receive, send)
    start = sent[0]
    return start["status"], dict(start["headers"])


def build(gate, limit=1, timeout=1.0):
    return ConcurrencyLimitMiddleware(
        gate,
        max_concurrent=limit,
        queue_timeout=timeout,
        exempt_paths={"/health/live"},
    )


async def let_tasks_run():
    await asyncio.sleep(0.02)


def test_requests_under_the_limit_all_run_at_once():
    async def scenario():
        gate = Gate()
        app = build(gate, limit=3)
        tasks = [asyncio.create_task(call(app)) for _ in range(3)]
        await let_tasks_run()
        assert gate.started == 3  # none of them had to wait
        gate.open.set()
        return [status for status, _ in await asyncio.gather(*tasks)]

    assert asyncio.run(scenario()) == [200, 200, 200]


def test_request_over_the_limit_waits_and_runs_when_a_slot_frees():
    async def scenario():
        gate = Gate()
        app = build(gate, limit=1, timeout=2.0)
        first = asyncio.create_task(call(app))
        second = asyncio.create_task(call(app))
        await let_tasks_run()
        assert gate.started == 1  # the second request is queued, not running
        gate.open.set()
        return (await first)[0], (await second)[0]

    assert asyncio.run(scenario()) == (200, 200)


def test_request_waiting_too_long_gets_503_with_retry_after():
    async def scenario():
        gate = Gate()
        app = build(gate, limit=1, timeout=0.05)
        first = asyncio.create_task(call(app))
        await let_tasks_run()
        shed_before = HTTP_REQUESTS_SHED._value.get()
        status, headers = await call(app)
        shed_after = HTTP_REQUESTS_SHED._value.get()
        gate.open.set()
        return status, headers, shed_after - shed_before, (await first)[0]

    status, headers, shed, first_status = asyncio.run(scenario())
    assert status == 503
    assert headers[b"retry-after"] == b"1"
    assert shed == 1
    assert first_status == 200  # the running request is not affected
    assert HTTP_REQUESTS_WAITING._value.get() == 0


def test_exempt_paths_are_served_while_the_app_is_full():
    async def scenario():
        gate = Gate()
        app = build(gate, limit=1, timeout=2.0)
        busy = asyncio.create_task(call(app))
        await let_tasks_run()
        gate.open.set()  # lets the exempt call finish immediately
        status, _ = await asyncio.wait_for(call(app, "/health/live"), timeout=1.0)
        await busy
        return status

    assert asyncio.run(scenario()) == 200


def test_slot_is_released_when_the_app_raises():
    async def scenario():
        gate = Gate()
        gate.open.set()
        gate.fail_next = True
        app = build(gate, limit=1, timeout=0.05)

        with pytest.raises(RuntimeError):
            await call(app)

        # If the failed request had kept its slot, this would be a 503.
        status, _ = await call(app)
        return status

    assert asyncio.run(scenario()) == 200


def test_non_http_scopes_pass_straight_through():
    async def scenario():
        seen = []

        async def inner(scope, receive, send):
            seen.append(scope["type"])

        app = build(inner, limit=1)
        await app({"type": "lifespan"}, None, None)
        return seen

    assert asyncio.run(scenario()) == ["lifespan"]


# --- Settings -----------------------------------------------------------

VALID = {
    "DATABASE_URL": "postgresql+psycopg://u:p@localhost:5432/db",
    "OTP_HMAC_SECRET": "a" * 40,
    "JWT_SECRET_KEY": "b" * 40,
    "APP_ENV": "development",
}


def build_settings(**overrides):
    return Settings(_env_file=None, **{**VALID, **overrides})


def test_default_limit_fits_inside_the_default_pool():
    config = build_settings()
    assert (
        0
        < config.MAX_CONCURRENT_REQUESTS
        <= (config.DB_POOL_SIZE + config.DB_MAX_OVERFLOW)
    )


def test_limit_above_pool_capacity_is_rejected():
    with pytest.raises(ValidationError, match="must not exceed"):
        build_settings(DB_POOL_SIZE=5, DB_MAX_OVERFLOW=5, MAX_CONCURRENT_REQUESTS=11)


def test_limit_can_be_turned_off():
    assert build_settings(MAX_CONCURRENT_REQUESTS=0).MAX_CONCURRENT_REQUESTS == 0


def test_negative_limit_and_zero_timeout_are_rejected():
    with pytest.raises(ValidationError):
        build_settings(MAX_CONCURRENT_REQUESTS=-1)

    with pytest.raises(ValidationError):
        build_settings(REQUEST_QUEUE_TIMEOUT_SECONDS=0)
