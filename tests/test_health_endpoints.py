import logging

import httpx
import pytest
from sqlalchemy.exc import OperationalError

from app.db.dependencies import get_db
from app.main import app


class BrokenSession:
    """Stands in for a database session when the database is down."""

    def execute(self, *args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))


@pytest.fixture
def database_down():
    def override_get_db():
        yield BrokenSession()

    app.dependency_overrides[get_db] = override_get_db

    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    )


@pytest.mark.asyncio
async def test_live_returns_200():
    async with make_client() as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


@pytest.mark.asyncio
async def test_live_still_returns_200_when_the_database_is_down(database_down):
    async with make_client() as client:
        response = await client.get("/health/live")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_ready_returns_200_when_the_database_answers(auth_client):
    response = await auth_client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


@pytest.mark.asyncio
async def test_ready_returns_503_without_details_when_the_database_is_down(
    database_down,
):
    async with make_client() as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert "connection refused" not in response.text


@pytest.mark.asyncio
async def test_health_checks_are_hidden_from_info_logs_but_visible_at_debug(caplog):
    caplog.set_level(logging.INFO, logger="app.access")

    async with make_client() as client:
        await client.get("/health/live")

    assert [r for r in caplog.records if r.name == "app.access"] == []

    caplog.set_level(logging.DEBUG, logger="app.access")

    async with make_client() as client:
        await client.get("/health/live")

    records = [r for r in caplog.records if r.name == "app.access"]

    assert len(records) == 1
    assert records[0].route == "/health/live"


@pytest.mark.asyncio
async def test_health_responses_carry_a_request_id():
    async with make_client() as client:
        response = await client.get("/health/live")

    assert len(response.headers["X-Request-ID"]) == 32
