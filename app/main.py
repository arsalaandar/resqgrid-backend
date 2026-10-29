from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.routes.admin import router as admin_router
from app.api.routes.auth import router as auth_router
from app.api.routes.incident_photos import (
    router as incident_photos_router,
)
from app.api.routes.incidents import router as incidents_router
from app.api.routes.me import router as me_router
from app.api.routes.staff_auth import router as staff_auth_router
from app.api.routes.token import router as token_router
from app.core.rate_limit import limiter

app = FastAPI(
    title="ResQGrid API",
    description="Emergency Incident Reporting and Response Platform",
    version="1.0.0",
)

# Register SlowAPI with the FastAPI application.
app.state.limiter = limiter
app.add_exception_handler(
    RateLimitExceeded,
    _rate_limit_exceeded_handler,
)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
):
    """Return 422 details without echoing the submitted values.

    FastAPI's default response includes each error's ``input``. That would
    send passwords and OTPs back to the client (and into proxy logs), and a
    NaN inside the input cannot be serialised, which turned a validation
    error into a 500.
    """
    errors = [
        {
            "loc": list(error.get("loc", ())),
            "msg": error.get("msg", "Invalid value."),
            "type": error.get("type", "value_error"),
        }
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})


@app.get("/")
def root():
    return {"message": "ResQGrid API is running"}


app.include_router(auth_router)
app.include_router(me_router)
app.include_router(admin_router)
app.include_router(incidents_router)
app.include_router(incident_photos_router)
app.include_router(staff_auth_router)
app.include_router(token_router)


def _fix_binary(node):
    """Swagger UI only shows a file picker for format: binary."""
    if isinstance(node, dict):
        if node.get("contentMediaType") == "application/octet-stream":
            node.pop("contentMediaType")
            node["format"] = "binary"

        for value in node.values():
            _fix_binary(value)

    elif isinstance(node, list):
        for item in node:
            _fix_binary(item)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    _fix_binary(schema)
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi
