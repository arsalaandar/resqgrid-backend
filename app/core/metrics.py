import anyio.to_thread
from prometheus_client import Counter, Gauge, Histogram

# Only these HTTP methods become label values. Clients can send any method
# name they like, and every distinct label value creates a new time series
# that Prometheus must store forever.
KNOWN_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})

HTTP_REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests handled.",
    ["method", "route", "status"],
)

HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "Time taken to handle an HTTP request, in seconds.",
    ["method", "route"],
    # Bucket edges, from 1 ms to 10 s. Percentiles such as p95 are estimated
    # from how many requests fell into each bucket, so fine edges at the low
    # end keep fast requests from all collapsing into one bucket.
    buckets=(
        0.001,
        0.0025,
        0.005,
        0.01,
        0.025,
        0.05,
        0.1,
        0.25,
        0.5,
        1.0,
        2.5,
        5.0,
        10.0,
    ),
)

HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "http_requests_in_progress",
    "Requests being handled right now.",
)


def method_label(method: str) -> str:
    return method if method in KNOWN_METHODS else "OTHER"


# --- Database -----------------------------------------------------------

DB_CONNECTIONS_OPENED = Counter(
    "db_connections_opened_total",
    "New database connections opened. Reusing a pooled one does not count.",
)

DB_QUERY_DURATION = Histogram(
    "db_query_duration_seconds",
    "Time the database took to run one statement, in seconds.",
    ["operation"],
    buckets=(0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)

# --- Thread pool --------------------------------------------------------
# Routes written as plain "def" run in a pool of worker threads, so this pool
# decides how many of them can run at once.

THREADPOOL_TOTAL = Gauge(
    "threadpool_threads_total",
    "Most worker threads that may run at once.",
)

THREADPOOL_IN_USE = Gauge(
    "threadpool_threads_in_use",
    "Worker threads busy right now.",
)

THREADPOOL_WAITING = Gauge(
    "threadpool_requests_waiting",
    "Requests waiting for a free worker thread.",
)


def update_threadpool_metrics() -> None:
    """Read the thread pool's current state. Must run inside the event loop."""
    limiter = anyio.to_thread.current_default_thread_limiter()

    THREADPOOL_TOTAL.set(limiter.total_tokens)
    THREADPOOL_IN_USE.set(limiter.borrowed_tokens)
    THREADPOOL_WAITING.set(limiter.statistics().tasks_waiting)
