import time

from prometheus_client import REGISTRY
from prometheus_client.core import GaugeMetricFamily
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.core.metrics import DB_CONNECTIONS_OPENED, DB_QUERY_DURATION

# Only these statement types become label values. Anything else is "OTHER",
# so the number of label values stays small whatever SQL is sent.
OPERATIONS = frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"})


def operation_label(statement: str) -> str:
    words = statement.split(None, 1)
    first = words[0].upper() if words else ""

    return first if first in OPERATIONS else "OTHER"


class PoolCollector:
    """Reads the connection pool's state each time Prometheus scrapes.

    A gauge like this describes "right now", so it is computed on demand
    instead of being updated by every query.
    """

    def __init__(self, engine: Engine, capacity: int) -> None:
        self.engine = engine
        self.capacity = capacity

    def collect(self):
        pool = self.engine.pool

        yield GaugeMetricFamily(
            "db_pool_capacity",
            "Most connections the pool may open (pool size plus overflow).",
            value=self.capacity,
        )
        yield GaugeMetricFamily(
            "db_pool_connections_in_use",
            "Connections checked out by requests right now.",
            value=pool.checkedout(),
        )
        yield GaugeMetricFamily(
            "db_pool_connections_idle",
            "Open connections waiting in the pool to be reused.",
            value=pool.checkedin(),
        )


def attach_query_metrics(engine: Engine) -> None:
    """Record connection opens and statement timings for this engine."""

    @event.listens_for(engine, "connect")
    def count_opened_connection(dbapi_connection, connection_record):
        DB_CONNECTIONS_OPENED.inc()

    @event.listens_for(engine, "before_cursor_execute")
    def start_timer(conn, cursor, statement, parameters, context, executemany):
        # Stored on the per-statement context, so a statement that fails
        # leaves nothing behind.
        context._query_started = time.perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def stop_timer(conn, cursor, statement, parameters, context, executemany):
        started = getattr(context, "_query_started", None)

        if started is not None:
            DB_QUERY_DURATION.labels(operation_label(statement)).observe(
                time.perf_counter() - started
            )


def instrument_engine(engine: Engine, capacity: int) -> None:
    REGISTRY.register(PoolCollector(engine, capacity))
    attach_query_metrics(engine)
