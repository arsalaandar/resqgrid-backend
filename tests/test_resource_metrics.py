import re

import httpx
import pytest
from prometheus_client import REGISTRY
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import QueuePool

from app.core.config import settings
from app.db.instrumentation import PoolCollector, attach_query_metrics, operation_label
from app.main import app


def sample(name: str, **labels) -> float:
    """Read one metric value. The registry is global, so tests compare deltas."""
    return REGISTRY.get_sample_value(name, labels) or 0.0


@pytest.fixture
def engine():
    """A small throwaway database with a real connection pool."""
    test_engine = create_engine(
        "sqlite://", poolclass=QueuePool, pool_size=2, max_overflow=1
    )
    attach_query_metrics(test_engine)

    yield test_engine

    test_engine.dispose()


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        ("SELECT 1", "SELECT"),
        ("  select * from users", "SELECT"),
        ("INSERT INTO users VALUES (1)", "INSERT"),
        ("update users set a = 1", "UPDATE"),
        ("DELETE FROM users", "DELETE"),
        ("WITH x AS (SELECT 1) SELECT * FROM x", "OTHER"),
        ("CREATE TABLE t (id int)", "OTHER"),
        ("", "OTHER"),
    ],
)
def test_statements_are_grouped_into_a_few_operations(statement, expected):
    assert operation_label(statement) == expected


def test_query_time_is_recorded_per_operation(engine):
    before = sample("db_query_duration_seconds_count", operation="SELECT")

    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))

    assert sample("db_query_duration_seconds_count", operation="SELECT") - before == 1
    assert sample("db_query_duration_seconds_sum", operation="SELECT") > 0


def test_a_failed_statement_is_not_recorded_and_does_not_break_later_ones(engine):
    before = sample("db_query_duration_seconds_count", operation="SELECT")

    with engine.connect() as connection:
        with pytest.raises(OperationalError):
            connection.execute(text("SELECT * FROM table_that_does_not_exist"))

        connection.execute(text("SELECT 1"))

    assert sample("db_query_duration_seconds_count", operation="SELECT") - before == 1


def test_only_new_connections_are_counted_not_reused_ones(engine):
    before = sample("db_connections_opened_total")

    for _ in range(3):
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    assert sample("db_connections_opened_total") - before == 1


def test_pool_collector_reports_connections_in_use_and_idle(engine):
    collector = PoolCollector(engine, capacity=3)

    def read() -> dict[str, float]:
        return {m.name: m.samples[0].value for m in collector.collect()}

    with engine.connect():
        busy = read()

    idle = read()

    assert busy["db_pool_capacity"] == 3
    assert busy["db_pool_connections_in_use"] == 1
    assert idle["db_pool_connections_in_use"] == 0
    assert idle["db_pool_connections_idle"] == 1


@pytest.mark.asyncio
async def test_metrics_endpoint_includes_pool_and_thread_pool_numbers(monkeypatch):
    monkeypatch.setattr(settings, "METRICS_TOKEN", None)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/metrics")

    body = response.text
    total = re.search(r"^threadpool_threads_total (\S+)$", body, re.MULTILINE)

    assert "db_pool_capacity " in body
    assert "db_pool_connections_in_use " in body
    assert "threadpool_requests_waiting " in body
    assert total is not None
    assert float(total.group(1)) > 0
