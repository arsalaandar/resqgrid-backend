import io
import json
import logging

import httpx
import pytest

from app.core.logging_config import JsonFormatter, RequestIdFilter
from app.main import app


def make_client(**transport_options) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, **transport_options),
        base_url="http://testserver",
    )


@pytest.fixture
def access_records(caplog):
    caplog.set_level(logging.INFO, logger="app.access")
    return lambda: [r for r in caplog.records if r.name == "app.access"]


@pytest.mark.asyncio
async def test_response_carries_a_generated_request_id():
    async with make_client() as client:
        response = await client.get("/")

    assert len(response.headers["X-Request-ID"]) == 32


@pytest.mark.asyncio
async def test_safe_incoming_request_id_is_reused():
    async with make_client() as client:
        response = await client.get("/", headers={"X-Request-ID": "trace-abc-12345"})

    assert response.headers["X-Request-ID"] == "trace-abc-12345"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_value",
    ["short", "x" * 100, "has spaces in it!", "semi;colon;12345"],
)
async def test_unsafe_incoming_request_id_is_replaced(bad_value):
    async with make_client() as client:
        response = await client.get("/", headers={"X-Request-ID": bad_value})

    assert response.headers["X-Request-ID"] != bad_value
    assert len(response.headers["X-Request-ID"]) == 32


@pytest.mark.asyncio
async def test_request_id_is_present_on_404_and_422():
    async with make_client() as client:
        not_found = await client.get("/no-such-page")
        invalid = await client.post("/api/v1/auth/staff/login", json={})

    assert not_found.status_code == 404
    assert invalid.status_code == 422
    assert "X-Request-ID" in not_found.headers
    assert "X-Request-ID" in invalid.headers


@pytest.mark.asyncio
async def test_access_log_uses_route_template_and_hides_query(access_records):
    async with make_client() as client:
        await client.get("/api/v1/incidents/12345?token=very-secret")

    record = access_records()[-1]

    assert record.route == "/api/v1/incidents/{incident_id}"
    assert record.method == "GET"
    assert record.status in (401, 403)
    assert record.duration_ms >= 0
    assert "12345" not in str(record.__dict__)
    assert "very-secret" not in str(record.__dict__)


@pytest.mark.asyncio
async def test_unknown_paths_are_logged_as_unmatched(access_records):
    async with make_client() as client:
        await client.get("/wp-admin/setup.php")

    record = access_records()[-1]

    assert record.route == "unmatched"
    assert record.status == 404


@pytest.mark.asyncio
async def test_unhandled_error_returns_generic_500_with_request_id(caplog):
    async def boom():
        raise RuntimeError("secret internal detail")

    app.add_api_route("/__boom", boom)

    try:
        async with make_client(raise_app_exceptions=False) as client:
            response = await client.get("/__boom")
    finally:
        app.router.routes.pop()

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error."}
    assert "secret internal detail" not in response.text

    request_id = response.headers["X-Request-ID"]
    errors = [r for r in caplog.records if r.getMessage() == "Unhandled exception"]

    assert len(errors) == 1
    assert errors[0].request_id == request_id


def test_json_formatter_writes_one_json_object_per_record():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RequestIdFilter())

    logger = logging.getLogger("test.json_formatter")
    logger.propagate = False
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    logger.info("hello", extra={"route": "/x", "status": 200, "password": "hunter2"})

    line = stream.getvalue().strip()
    data = json.loads(line)

    assert data["message"] == "hello"
    assert data["level"] == "INFO"
    assert data["route"] == "/x"
    assert data["status"] == 200
    assert data["request_id"] == "-"
    # Fields outside the allow-list are dropped, so secrets cannot leak by accident.
    assert "password" not in data
    assert "hunter2" not in line


@pytest.mark.asyncio
async def test_failed_login_never_writes_the_password_to_logs(auth_client, caplog):
    caplog.set_level(logging.DEBUG)

    response = await auth_client.post(
        "/api/v1/auth/staff/login",
        json={"phone": "+911234567890", "password": "Sup3r-Secret-Passw0rd"},
    )

    assert response.status_code == 401
    assert "Sup3r-Secret-Passw0rd" not in caplog.text
