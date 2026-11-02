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
    # Bucket edges, from 5 ms to 10 s. Percentiles such as p95 are estimated
    # from how many requests fell into each bucket.
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "http_requests_in_progress",
    "Requests being handled right now.",
)


def method_label(method: str) -> str:
    return method if method in KNOWN_METHODS else "OTHER"
