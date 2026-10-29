"""Tests for FastAPI application configuration and OpenAPI customization."""

import copy

import httpx
import pytest

import app.main as main


def test_application_metadata():
    assert main.app.title == "ResQGrid API"
    assert main.app.description == "Emergency Incident Reporting and Response Platform"
    assert main.app.version == "1.0.0"


@pytest.mark.asyncio
async def test_root_endpoint():
    transport = httpx.ASGITransport(app=main.app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert response.json() == {"message": "ResQGrid API is running"}


def test_default_documentation_routes_are_registered():
    paths = {getattr(route, "path", None) for route in main.app.routes}

    assert "/" in paths
    assert "/openapi.json" in paths
    assert "/docs" in paths
    assert "/redoc" in paths


def test_application_includes_all_expected_routers():
    expected_routers = (
        main.auth_router,
        main.me_router,
        main.admin_router,
        main.incidents_router,
        main.incident_photos_router,
        main.staff_auth_router,
        main.token_router,
    )

    schema = main.app.openapi()
    registered_paths = schema["paths"]

    for router in expected_routers:
        for route in router.routes:
            path = getattr(route, "path", None)
            methods = getattr(route, "methods", set()) or set()

            # OpenAPI excludes routes that do not declare a path or are
            # explicitly excluded from the generated schema.
            if path is None or getattr(route, "include_in_schema", True) is False:
                continue

            assert path in registered_paths, (
                f"Router endpoint {path} was not registered in OpenAPI"
            )

            registered_methods = {method.upper() for method in registered_paths[path]}

            for method in methods:
                assert method.upper() in registered_methods, (
                    f"Method {method} for router endpoint {path} "
                    "was not registered in OpenAPI"
                )


def test_fix_binary_converts_octet_stream_schema_recursively():
    schema = {
        "components": {
            "schemas": {
                "Upload": {
                    "type": "string",
                    "contentMediaType": "application/octet-stream",
                }
            }
        },
        "paths": [
            {
                "requestBody": {
                    "contentMediaType": "application/octet-stream",
                    "nested": [
                        {
                            "contentMediaType": "application/octet-stream",
                            "type": "string",
                        }
                    ],
                }
            }
        ],
    }

    main._fix_binary(schema)

    upload = schema["components"]["schemas"]["Upload"]
    assert "contentMediaType" not in upload
    assert upload["format"] == "binary"

    path_item = schema["paths"][0]["requestBody"]
    assert "contentMediaType" not in path_item
    assert path_item["format"] == "binary"
    assert path_item["nested"][0]["format"] == "binary"
    assert "contentMediaType" not in path_item["nested"][0]


@pytest.mark.parametrize(
    "value",
    [
        None,
        "ordinary text",
        123,
        True,
        [],
        {},
        {"type": "string", "contentMediaType": "text/plain"},
    ],
)
def test_fix_binary_handles_nonmatching_values_without_error(value):
    original = copy.deepcopy(value)

    main._fix_binary(value)

    assert value == original


def test_fix_binary_handles_lists_and_mixed_nested_values():
    schema = [
        {"contentMediaType": "application/octet-stream"},
        "text",
        None,
        [{"contentMediaType": "application/octet-stream"}],
    ]

    main._fix_binary(schema)

    assert schema[0] == {"format": "binary"}
    assert schema[1] == "text"
    assert schema[2] is None
    assert schema[3][0] == {"format": "binary"}


def test_custom_openapi_returns_cached_schema_without_regenerating(monkeypatch):
    cached_schema = {"openapi": "cached-test-schema"}
    original_schema = main.app.openapi_schema
    original_get_openapi = main.get_openapi

    try:
        main.app.openapi_schema = cached_schema

        def unexpected_openapi_call(**kwargs):
            pytest.fail("get_openapi should not be called when schema is cached")

        monkeypatch.setattr(main, "get_openapi", unexpected_openapi_call)

        assert main.custom_openapi() is cached_schema
    finally:
        main.app.openapi_schema = original_schema
        monkeypatch.setattr(main, "get_openapi", original_get_openapi)


def test_custom_openapi_generates_and_caches_schema(monkeypatch):
    original_schema = main.app.openapi_schema
    generated_schema = {
        "openapi": "3.1.0",
        "components": {
            "schemas": {
                "Upload": {
                    "type": "string",
                    "contentMediaType": "application/octet-stream",
                }
            }
        },
    }
    calls = []

    def fake_get_openapi(**kwargs):
        calls.append(kwargs)
        return copy.deepcopy(generated_schema)

    try:
        main.app.openapi_schema = None
        monkeypatch.setattr(main, "get_openapi", fake_get_openapi)

        first = main.custom_openapi()
        second = main.custom_openapi()

        assert first is second
        assert main.app.openapi_schema is first
        assert len(calls) == 1
        assert calls[0]["title"] == main.app.title
        assert calls[0]["version"] == main.app.version
        assert calls[0]["description"] == main.app.description
        assert calls[0]["routes"] is main.app.routes
        assert first["components"]["schemas"]["Upload"] == {
            "type": "string",
            "format": "binary",
        }
    finally:
        main.app.openapi_schema = original_schema


def test_app_openapi_is_custom_openapi_function():
    assert main.app.openapi is main.custom_openapi
