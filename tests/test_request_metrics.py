import httpx
import pytest
from prometheus_client import REGISTRY

from app.core.config import settings
from app.main import app


def make_client(**transport_options) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, **transport_options),
        base_url="http://testserver",
    )


def sample(name: str, **labels) -> float:
    """Read one metric value. The registry is global, so tests compare deltas."""
    return REGISTRY.get_sample_value(name, labels) or 0.0


def all_label_values() -> set[str]:
    return {
        value
        for metric in REGISTRY.collect()
        for s in metric.samples
        for value in s.labels.values()
    }


@pytest.mark.asyncio
async def test_request_is_counted_by_route_template_and_status():
    route = "/api/v1/incidents/{incident_id}"

    async with make_client() as client:
        before = sample(
            "http_requests_total", method="GET", route=route, status="401"
        ) + sample("http_requests_total", method="GET", route=route, status="403")
        await client.get("/api/v1/incidents/987654")

    after = sample(
        "http_requests_total", method="GET", route=route, status="401"
    ) + sample("http_requests_total", method="GET", route=route, status="403")

    assert after - before == 1
    assert "/api/v1/incidents/987654" not in all_label_values()


@pytest.mark.asyncio
async def test_request_duration_is_recorded_in_a_histogram():
    labels = {"method": "GET", "route": "/"}
    before = sample("http_request_duration_seconds_count", **labels)

    async with make_client() as client:
        await client.get("/")

    assert sample("http_request_duration_seconds_count", **labels) - before == 1
    assert sample("http_request_duration_seconds_sum", **labels) > 0
    assert sample("http_request_duration_seconds_bucket", le="+Inf", **labels) >= 1


@pytest.mark.asyncio
async def test_unknown_paths_share_one_unmatched_label():
    before = sample(
        "http_requests_total", method="GET", route="unmatched", status="404"
    )

    async with make_client() as client:
        await client.get("/random-scan-one")
        await client.get("/random-scan-two")

    after = sample("http_requests_total", method="GET", route="unmatched", status="404")

    assert after - before == 2
    assert not any("random-scan" in value for value in all_label_values())


@pytest.mark.asyncio
async def test_unusual_http_methods_are_grouped_as_other():
    async with make_client() as client:
        await client.request("WEIRDMETHOD", "/")

    assert "WEIRDMETHOD" not in all_label_values()
    assert "OTHER" in all_label_values()


@pytest.mark.asyncio
async def test_in_progress_gauge_counts_the_request_being_handled():
    async def peek():
        return {"in_progress": sample("http_requests_in_progress")}

    baseline = sample("http_requests_in_progress")
    app.add_api_route("/__peek", peek)

    try:
        async with make_client() as client:
            response = await client.get("/__peek")
    finally:
        app.router.routes.pop()

    assert response.json()["in_progress"] == baseline + 1
    assert sample("http_requests_in_progress") == baseline


@pytest.mark.asyncio
async def test_unhandled_errors_are_counted_as_500():
    async def boom():
        raise RuntimeError("boom")

    app.add_api_route("/__metrics_boom", boom)
    labels = {"method": "GET", "route": "/__metrics_boom", "status": "500"}
    before = sample("http_requests_total", **labels)

    try:
        async with make_client(raise_app_exceptions=False) as client:
            await client.get("/__metrics_boom")
    finally:
        app.router.routes.pop()

    assert sample("http_requests_total", **labels) - before == 1


@pytest.mark.asyncio
async def test_metrics_endpoint_serves_prometheus_text(monkeypatch):
    monkeypatch.setattr(settings, "METRICS_TOKEN", None)

    async with make_client() as client:
        await client.get("/")
        response = await client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "# TYPE http_requests_total counter" in response.text
    assert "http_request_duration_seconds_bucket" in response.text


@pytest.mark.asyncio
async def test_metrics_endpoint_is_not_counted_in_its_own_numbers(monkeypatch):
    monkeypatch.setattr(settings, "METRICS_TOKEN", None)

    async with make_client() as client:
        await client.get("/metrics")
        await client.get("/metrics")

    assert "/metrics" not in all_label_values()


@pytest.mark.asyncio
async def test_metrics_endpoint_requires_the_token_when_one_is_set(monkeypatch):
    monkeypatch.setattr(settings, "METRICS_TOKEN", "a-long-enough-token-1234")

    async with make_client() as client:
        missing = await client.get("/metrics")
        wrong = await client.get("/metrics", headers={"Authorization": "Bearer nope"})
        right = await client.get(
            "/metrics",
            headers={"Authorization": "Bearer a-long-enough-token-1234"},
        )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert right.status_code == 200


def test_metrics_endpoint_is_hidden_from_the_api_docs():
    assert "/metrics" not in app.openapi()["paths"]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/docs", "/openapi.json"])
async def test_built_in_pages_are_labelled_with_their_own_route(path):
    labels = {"method": "GET", "route": path, "status": "200"}
    before = sample("http_requests_total", **labels)

    async with make_client() as client:
        response = await client.get(path)

    assert response.status_code == 200
    assert sample("http_requests_total", **labels) - before == 1
