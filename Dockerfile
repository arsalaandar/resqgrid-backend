# syntax=docker/dockerfile:1

# ---- Stage 1: build the virtual environment --------------------------------
FROM python:3.13-slim AS build

# uv comes from its official image. Pinning the version keeps builds repeatable.
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first. This layer is rebuilt only when the lock file changes,
# so ordinary code edits rebuild in seconds.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ---- Stage 2: the runtime image --------------------------------------------
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

# Run as an unprivileged user, so a bug in the app cannot act as root.
RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app --no-create-home app

WORKDIR /app

# Only what the app needs at runtime. Tests, docs and monitoring stay out.
COPY --from=build --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app app ./app
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app scripts ./scripts

RUN mkdir -p /app/storage/incident_photos \
    && chown -R app:app /app/storage

USER app

EXPOSE 8000

# "Liveness" only: it must not depend on the database (see /health/live).
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]