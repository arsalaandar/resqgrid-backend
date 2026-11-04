# ResQGrid

[![CI](https://github.com/arsalaandar/resqgrid-backend/actions/workflows/ci.yml/badge.svg)](https://github.com/arsalaandar/resqgrid-backend/actions/workflows/ci.yml)

ResQGrid is the backend for an emergency incident reporting platform. Citizens and field officials report incidents with a location and photographs, officials review what happens in their area, and admins manage staff accounts. A later milestone shares incidents with an external Decision Support System (DSS).

The API is built with FastAPI and PostgreSQL. A Flutter mobile client is planned; this repository contains only the backend. The project is also a hands-on exercise in production-style backend engineering: security, testing, CI, observability and capacity planning.

> **Status:** authentication, role-based access control, incident reporting and photo upload are implemented and covered by about 300 automated tests that run against a real PostgreSQL database in CI. Structured logs, health checks, Prometheus metrics, a Grafana dashboard and alert rules are in place. A **demo** runs on Render's free tier (see [Deployment](#deployment)); it is not production-ready. See [Known limitations](#known-limitations) and [Roadmap](#roadmap).

## Contents

- [Technology stack](#technology-stack)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Project structure](#project-structure)
- [What is implemented](#what-is-implemented)
- [API endpoints](#api-endpoints)
- [Roles and permissions](#roles-and-permissions)
- [Incident lifecycle](#incident-lifecycle)
- [Rate limiting](#rate-limiting)
- [Database and migrations](#database-and-migrations)
- [Observability](#observability)
- [Testing and CI](#testing-and-ci)
- [Scripts](#scripts)
- [Deployment](#deployment)
- [Development workflow](#development-workflow)
- [Security design](#security-design)
- [Known limitations](#known-limitations)
- [Roadmap](#roadmap)
- [Change log](#change-log)
- [Maintaining this README](#maintaining-this-readme)

## Technology stack

| Area | Technology |
|---|---|
| API | FastAPI on Python 3.13 |
| Database | PostgreSQL 16, SQLAlchemy 2, Alembic migrations |
| Authentication | JWT access tokens and opaque, rotating refresh tokens |
| Password hashing | `pwdlib` with Argon2id |
| Images | Pillow |
| Rate limiting | SlowAPI (in-memory in development, Redis in production) |
| Observability | Structured JSON logs, Prometheus metrics, Grafana dashboard, Prometheus alert rules |
| Packaging | `uv` with a committed `uv.lock` |
| Tests and lint | pytest, pytest-asyncio, httpx, Ruff, promtool (alert rules) |
| CI | GitHub Actions, Dependabot |
| Hosting (demo) | Render free tier |

## Quick start

You need Python 3.13, [uv](https://docs.astral.sh/uv/), and Docker (for PostgreSQL).

```powershell
git clone https://github.com/arsalaandar/resqgrid-backend.git
cd resqgrid-backend

# 1. Install the exact locked dependencies into .venv
uv sync
.\.venv\Scripts\Activate.ps1

# 2. Configure the environment
Copy-Item .env.example .env
# Edit .env: set real values (see Configuration below)

# 3. Start PostgreSQL (bound to 127.0.0.1 only)
docker compose up -d

# 4. Create the schema
alembic upgrade head

# 5. Create the first SUPER_ADMIN (prompts for phone and password)
python -m scripts.bootstrap_super_admin

# 6. Run the API
python -m uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for the interactive API documentation.

Without activating the environment, prefix commands with `uv run`, for example `uv run pytest`.

Logs are JSON lines by default. For easier reading in a terminal, add `LOG_FORMAT=text` to `.env`. To run the monitoring stack (Prometheus and Grafana), see [Observability](#observability).

## Configuration

Settings are read from environment variables or a local `.env` file, which is ignored by Git. Copy `.env.example` as a starting point and **never commit real secrets**. Generate secrets with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | required | Application database (`postgresql+psycopg://...`) |
| `TEST_DATABASE_URL` | none | Test database. Must be named `resqgrid_test` |
| `APP_ENV` | `development` | `development`, `testing`, `staging` or `production` |
| `JWT_SECRET_KEY` | required | Signs access tokens. At least 32 characters |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | Access token lifetime |
| `JWT_ISSUER` / `JWT_AUDIENCE` | `resqgrid-api` / `resqgrid-mobile` | Token claims checked on every request |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Lifetime of one refresh token |
| `JWT_SESSION_ABSOLUTE_EXPIRE_DAYS` | `30` | Maximum session age, however often it is refreshed |
| `OTP_PROVIDER` | `console` | OTP delivery provider. `console` is allowed only in development |
| `OTP_HMAC_SECRET` | required | Keys the OTP verifier. At least 32 characters and different from the JWT secret |
| `OTP_TTL_SECONDS` | `300` | OTP validity |
| `OTP_MAX_ATTEMPTS` | `5` | Wrong guesses allowed per OTP |
| `OTP_RESEND_COOLDOWN_SECONDS` | `60` | Minimum gap between OTPs for one phone number |
| `OTP_MAX_REQUESTS_PER_HOUR` / `_PER_DAY` | `5` / `10` | Per-phone OTP request caps |
| `RATE_LIMIT_STORAGE_URI` | `memory://` | Use `redis://host:6379/0` in staging and production |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `10` / `20` | Connection pool sizing |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR` |
| `LOG_FORMAT` | `json` | `json` for servers and log tools, `text` for reading logs in a terminal |
| `METRICS_ENABLED` | `true` | Serve `/metrics`. When `false`, the endpoint does not exist |
| `METRICS_TOKEN` | none | Bearer token required by `/metrics` when set. At least 32 characters. Required in staging and production while metrics are enabled, and must differ from the JWT and OTP secrets |
| `INCIDENT_PHOTO_STORAGE_DIR` | `storage/incident_photos` | Where photos are written |
| `INCIDENT_PHOTO_MIN_COUNT` / `_MAX_COUNT` | `3` / `10` | Photos required to report an incident |
| `INCIDENT_PHOTO_MAX_SIZE_BYTES` | `10 MiB` | Per-photo size limit |
| `INCIDENT_PHOTO_MAX_TOTAL_BYTES` | `60 MiB` | Combined size limit per upload |
| `INCIDENT_PHOTO_MAX_PIXELS` | `40,000,000` | Decoded pixel limit per photo |
| `INCIDENT_PHOTO_MAX_DISTANCE_METERS` | `100` | Maximum photo-to-incident GPS distance |

The app validates its settings at startup and refuses to start if:

- either secret is shorter than 32 characters, or the two secrets are identical;
- `JWT_SESSION_ABSOLUTE_EXPIRE_DAYS` is shorter than `JWT_REFRESH_TOKEN_EXPIRE_DAYS`;
- `APP_ENV` is `staging` or `production` while `OTP_PROVIDER` is `console` or `RATE_LIMIT_STORAGE_URI` is `memory://`;
- `APP_ENV` is `staging` or `production` while metrics are enabled and `METRICS_TOKEN` is missing or equal to the JWT or OTP secret.

## Project structure

```
app/
  api/routes/     HTTP endpoints: auth, staff_auth, token, me, incidents,
                  incident_photos, admin, health, metrics
  core/           settings, security, roles, rate limiting, logging,
                  request middleware, metrics definitions
  db/             engine, sessions, query and connection-pool instrumentation
  models/         SQLAlchemy models
  schemas/        request and response models
  services/       business logic: OTP, refresh tokens, incidents, photos
  providers/otp/  OTP delivery providers (console only so far)
alembic/          database migrations
scripts/          operational scripts and a traffic generator
tests/            automated tests (run against a real PostgreSQL database)
monitoring/       Prometheus config, alert rules and tests, Grafana dashboard
.github/          CI workflow and Dependabot configuration
```

## What is implemented

**Authentication**

- Citizen login with phone number and OTP. Codes are stored only as HMAC verifiers. Requests are throttled per phone number, and a new code invalidates earlier ones.
- Staff login (`SUPER_ADMIN`, `ADMIN`, `OFFICIAL`) with phone and password. Login performs one password verification even for unknown numbers, so response time does not reveal which accounts exist. Outdated password hashes are upgraded automatically.
- New staff accounts have a temporary password and cannot use any endpoint except password change until they set their own.

**Tokens and sessions**

- Short-lived access tokens carry a `token_version`. A password change or deactivation invalidates them immediately.
- Refresh tokens are hashed at rest, rotate on every use, belong to a session family with an absolute lifetime, and reuse of a rotated token revokes the whole family. A credential change or deactivation revokes every session the user holds.

**Accounts**

- A `SUPER_ADMIN` creates admins. Admins and super admins create officials, each with an assigned district and tehsil validated against the official J&K list in `app/core/incident_options.py`.

**Incidents**

- A report is created as a `DRAFT` and becomes `REPORTED` only when 3 to 10 valid photos are uploaded.
- Photos are validated by real image content (JPEG, PNG, WEBP), size, pixel count and embedded GPS, which must lie within 100 m of the incident. Stored copies are re-encoded **without EXIF or GPS metadata**.
- Input is validated: known categories, districts and tehsils, bounded counts, a size limit on free-form departmental details, and no future incident times.
- Access is role-aware: citizens see their own incidents, officials see submitted incidents in their jurisdiction, and admins see everything through a filterable, paginated list.

**Platform**

- Alembic migrations, a startup configuration check, validation errors that never echo submitted values, a script to purge abandoned drafts, and a CI pipeline.
- Structured logs with request IDs, liveness and readiness endpoints, Prometheus metrics, a Grafana dashboard and alert rules (see [Observability](#observability)).

## API endpoints

All paths are under `/api/v1` unless shown. "Any user" means any authenticated account that has no pending password change.

| Method | Path | Access | Purpose |
|---|---|---|---|
| GET | `/` (no prefix) | Public | Returns a "running" message. Use the health endpoints for checks |
| GET | `/health/live` (no prefix) | Public | Liveness: the process is running. Never touches the database |
| GET | `/health/ready` (no prefix) | Public | Readiness: runs `SELECT 1`. Returns `503` with a generic body if the database is unavailable |
| GET | `/metrics` (no prefix) | Bearer `METRICS_TOKEN` when set | Prometheus metrics. Hidden from `/docs` |
| POST | `/auth/citizen/request-otp` | Public | Request an OTP. The response is identical whether or not one was sent |
| POST | `/auth/citizen/verify-otp` | Public | Exchange a valid OTP for tokens, creating the citizen account if needed |
| POST | `/auth/staff/login` | Public | Staff phone and password login |
| POST | `/auth/staff/change-password` | Staff | Change password. Required for new accounts |
| POST | `/auth/refresh` | Public (refresh token) | Rotate a refresh token and get a new access token |
| POST | `/auth/logout` | Public (refresh token) | Revoke a session. Always succeeds |
| GET | `/me` | Any user | The caller's profile |
| GET | `/incidents/options` | Public | Categories, severity levels, damage situations, districts |
| GET | `/incidents/options/tehsils` | Public | Tehsils for a district |
| POST | `/incidents` | Any user | Create a `DRAFT` incident. Officials may only report inside their jurisdiction |
| POST | `/incidents/{id}/photos` | Reporter | Upload 3 to 10 photos and submit the incident |
| GET | `/incidents/my` | Any user | The caller's own incidents (paginated) |
| GET | `/incidents/assigned` | Official | Submitted incidents in the official's district and tehsil |
| GET | `/incidents/{id}` | Role-dependent | Citizens: own. Officials: own jurisdiction. Admins: all |
| GET | `/admin/check-access` | Admin, Super admin | Confirms admin access |
| POST | `/admin/admins` | Super admin | Create an admin |
| POST | `/admin/officials` | Admin, Super admin | Create an official |
| GET | `/admin/incidents` | Admin, Super admin | Filter by district, tehsil, category, status and date; paginated |

The authoritative reference is the generated schema at `/docs`, `/redoc` and `/openapi.json`.

## Roles and permissions

| Role | Can do |
|---|---|
| `CITIZEN` | Log in with OTP, report incidents, view own incidents |
| `OFFICIAL` | Staff login, report inside their jurisdiction, view submitted incidents in their jurisdiction |
| `ADMIN` | Everything an official can, create officials, list and filter all incidents |
| `SUPER_ADMIN` | Everything an admin can, create admins |

Roles are defined once in `app/core/roles.py`. An unknown role name passed to `require_roles` fails at startup instead of silently denying access.

## Incident lifecycle

```
POST /incidents          POST /incidents/{id}/photos
   (create)       -->        (3-10 valid photos)
                  DRAFT  -------------------------->  REPORTED
```

- A `DRAFT` is visible to its author and to admins. Other officials and citizens cannot see it.
- Photo upload and the status change happen in one database transaction. If any photo is rejected, no files are kept and the incident stays a draft.
- Drafts that are never completed can be removed with `python -m scripts.purge_stale_drafts`.
- Further statuses (verification, assignment, resolution) are not implemented yet.

## Rate limiting

| Endpoint | Limit (per IP) |
|---|---:|
| `POST /auth/citizen/request-otp` | 3 per minute |
| `POST /auth/citizen/verify-otp` | 10 per minute |
| `POST /auth/staff/login` | 5 per minute |
| `POST /auth/staff/change-password` | 5 per minute |
| `POST /auth/refresh` | 30 per minute |
| `POST /auth/logout` | 30 per minute |

Violations return `429`. OTP sends are also limited **per phone number** in the OTP service, and a throttled request receives the same response as a successful one.

Behind a reverse proxy, start Uvicorn with `--proxy-headers --forwarded-allow-ips=<proxy IP>` so the real client IP is used. Never trust forwarded headers from arbitrary clients.

## Database and migrations

PostgreSQL is accessed through SQLAlchemy; the schema is managed only by Alembic.

```powershell
alembic upgrade head                           # apply migrations
alembic revision --autogenerate -m "describe"  # create a migration from model changes
alembic check                                  # fail if models and migrations disagree
```

Review every autogenerated migration before committing it. After pulling a migration, run `alembic upgrade head` against **both** your development and test databases.

Tables: `users`, `otp_challenges`, `refresh_tokens`, `incidents`, `incident_photos`.

Connections come from a pool (`DB_POOL_SIZE` plus `DB_MAX_OVERFLOW`). Opening a connection gives up after 5 seconds, so a database outage fails requests quickly instead of hanging.

## Observability

Logs say what happened to one request, metrics say how the system is doing overall, and alerts say when to look.

### Logs and request IDs

- Every request writes one access-log line. In JSON mode the fields are `time`, `level`, `logger`, `message`, `request_id`, `method`, `route`, `status`, `duration_ms` and `client_ip` (plus `exception` for errors).
- `route` is the **route template** (`/api/v1/incidents/{incident_id}`), never the real URL, so IDs and query strings stay out of the logs. Unknown paths are logged as `unmatched`.
- Every response carries an `X-Request-ID` header, and the same ID appears on every log line written while handling that request. A caller may supply its own ID only if it is 8 to 64 characters of letters, digits and dashes; anything else is replaced, which prevents forged log lines.
- Only an allow-list of fields is ever written to the access log. Request bodies, passwords, tokens and OTPs are never logged.
- Unhandled errors are logged once with a stack trace and the request ID, and the client receives a generic `500` response.
- Health checks and `/metrics` requests are logged at `DEBUG` only, to keep normal logs readable.

### Health checks

- `GET /health/live` answers whether the process is running. It never touches the database, so a database outage does not make the platform restart a healthy app.
- `GET /health/ready` runs `SELECT 1` and returns `503` with `{"status": "unavailable"}` if the database does not answer. The failure reason is logged but never returned.

### Metrics

`GET /metrics` serves Prometheus metrics. When `METRICS_TOKEN` is set, the request must carry `Authorization: Bearer <token>`; the token is compared in constant time.

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `http_requests_total` | counter | `method`, `route`, `status` | Requests handled |
| `http_request_duration_seconds` | histogram | `method`, `route` | Time to handle a request |
| `http_requests_in_progress` | gauge | none | Requests being handled right now |
| `db_pool_capacity` | gauge | none | Pool size plus overflow |
| `db_pool_connections_in_use` | gauge | none | Connections checked out right now |
| `db_pool_connections_idle` | gauge | none | Open connections waiting in the pool |
| `db_connections_opened_total` | counter | none | New database connections opened |
| `db_query_duration_seconds` | histogram | `operation` | Time per statement (`SELECT`, `INSERT`, `UPDATE`, `DELETE`, `OTHER`) |
| `threadpool_threads_total` | gauge | none | Worker threads available to plain `def` routes |
| `threadpool_threads_in_use` | gauge | none | Worker threads busy right now |
| `threadpool_requests_waiting` | gauge | none | Requests waiting for a free worker thread |

Label values are deliberately bounded: routes are templates, unusual HTTP methods become `OTHER`, and SQL text is reduced to five operation names. Unbounded labels (raw URLs, user IDs, phone numbers) would make the number of stored time series grow without limit. `/metrics` does not count itself.

Metrics live in the memory of one process. With several Uvicorn workers each would report its own numbers; see [Known limitations](#known-limitations).

### Monitoring stack (local)

Prometheus and Grafana run in Docker Compose behind a `monitoring` profile, so a plain `docker compose up -d` still starts only PostgreSQL.

1. Create `monitoring/metrics_token` containing only the metrics token, on one line. The file is Git-ignored (`monitoring/metrics_token*`). Create it **before** starting the stack, otherwise Docker creates a folder with that name.
2. `monitoring/prometheus.yml` scrapes the Render demo by default. To watch an app running on your own computer instead, comment out the `resqgrid-render` job and uncomment `resqgrid-local`.
3. Start the stack:

```powershell
docker compose --profile monitoring up -d
```

| Service | Address | Notes |
|---|---|---|
| Prometheus | `http://localhost:9090` | `/targets` shows whether scraping works, `/alerts` shows alert state |
| Grafana | `http://localhost:3000` | Login `admin` with the password from `GRAFANA_ADMIN_PASSWORD` (default `admin`; local only, bound to 127.0.0.1) |

Prometheus pulls from the app every 15 seconds, so it can watch a deployed app from any machine that can reach its URL. Data is only collected while the stack is running.

Generate traffic for the graphs with:

```powershell
python -m scripts.demo_traffic --url http://127.0.0.1:8000 --seconds 60 --rps 20
```

Keep the rate low when pointing it at a deployed free-tier service.

### Dashboard

Grafana loads `monitoring/grafana/dashboards/resqgrid-overview.json` automatically. It has 15 panels in two groups:

- **Service health (RED):** requests per second, server error rate, p95 latency, requests in progress, traffic by route, responses by status code, latency percentiles, average latency by route, slowest routes.
- **Resources (why latency changes):** database connections in use against capacity, new connections per minute, query time and query rate by operation, the share of request time spent in the database, and worker threads busy against total and waiting.

### Alerts

Rules live in `monitoring/alerts.yml` and are evaluated by Prometheus every 15 seconds.

| Alert | Fires when | Severity |
|---|---|---|
| `AppDown` | Prometheus cannot scrape the app for 2 minutes | critical |
| `HighServerErrorRate` | More than 5% of API requests return 5xx for 5 minutes (needs at least 20 requests in 5 minutes) | critical |
| `RepeatedServerErrors` | At least 5 API requests return 5xx within 10 minutes. Covers quiet periods where a percentage is meaningless | warning |
| `HighLatency` | The slowest 5% of API requests exceed 2 seconds for 10 minutes. Photo uploads are excluded | warning |

The rules have unit tests in `monitoring/alerts_test.yml`. They feed fake metric series to the rules and check that each alert fires when it should and stays quiet when it should not:

```powershell
docker run --rm -v "${PWD}/monitoring:/m:ro" --entrypoint promtool prom/prometheus:v3.5.0 test rules /m/alerts_test.yml
```

Alertmanager is not configured, so alerts appear on the Prometheus page but do not reach a phone or inbox yet. The thresholds are provisional until a load test shows real behavior.

## Testing and CI

Tests run against a dedicated PostgreSQL database named `resqgrid_test`. A safety check in `tests/conftest.py` refuses any other database name and refuses the application database. Each test runs inside a transaction that is rolled back, and rate-limit counters are reset before every test.

```powershell
# One-time: create and migrate the test database
docker exec resqgrid-postgres psql -U resqgrid -d resqgrid -c "CREATE DATABASE resqgrid_test;"
$env:DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@localhost:5432/resqgrid_test"
alembic upgrade head
Remove-Item Env:DATABASE_URL
```

Put `TEST_DATABASE_URL` in `.env` (`pytest-dotenv` loads it), then:

```powershell
python -m pytest -q            # run everything
ruff check .                   # lint
ruff format .                  # format
```

GitHub Actions (`.github/workflows/ci.yml`) runs lint, a formatting check, and the full test suite with a coverage report against a PostgreSQL service container on every push to `main` and every pull request. Dependencies are installed from `uv.lock` with `--frozen`, so a stale lock file fails the build. Dependabot proposes updates to GitHub Actions and Python packages weekly; CI tests each one before you merge it.

`main` is protected by a ruleset that requires a pull request and passing `lint` and `test` checks. The alert-rule tests (`promtool`) are run by hand and are not part of CI yet.

## Scripts

| Command | Purpose |
|---|---|
| `python -m scripts.bootstrap_super_admin` | Create the first `SUPER_ADMIN`. Prompts for the phone and password; nothing is stored in code or logs |
| `python -m scripts.purge_stale_drafts --days 7` | Delete `DRAFT` incidents older than the given number of days. Suitable for a daily scheduled job |
| `python -m scripts.demo_traffic --seconds 60 --rps 20` | Send a mix of requests to a running app so the dashboard has data. Options: `--url`, `--seconds`, `--rps` |

## Deployment

A demo runs on Render's free tier at `https://resqgrid-backend-uw99.onrender.com` (API documentation at `/docs`). It exists to show the app running and to give the monitoring stack something real to watch. Be aware that:

- The free instance sleeps when idle, so the first request after a quiet period can take about a minute.
- It runs with `APP_ENV=development`, because no real SMS provider or Redis is configured yet. OTP codes are **printed to the server log**, and no SMS is sent.
- Uploaded photos are stored on the instance's local disk and disappear when it restarts or redeploys.
- `/metrics` is protected by a bearer token.

Render service settings for this repository:

| Setting | Value |
|---|---|
| Build command | `uv sync --frozen && uv cache prune --ci` |
| Start command | `uv run --no-sync alembic upgrade head && uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Python version | Read from `.python-version` (3.13) |
| Health check path | `/health/live` |
| Environment | `APP_ENV`, `DATABASE_URL` (with the `postgresql+psycopg://` prefix), `JWT_SECRET_KEY`, `OTP_HMAC_SECRET`, `METRICS_TOKEN` |

Use `/health/live` for the platform health check. A check that depends on the database (`/health/ready`) would make the platform restart a healthy app during a database outage, which does not fix the database. Create the first super admin by running `python -m scripts.bootstrap_super_admin` locally with `DATABASE_URL` pointed at the hosted database.

A real production setup needs the items under [Roadmap](#roadmap): an SMS provider, Redis for shared rate limits, object storage for photos, a Dockerfile, backups and `APP_ENV=production`.

## Development workflow

- Work on a branch, open a pull request into `main`, and merge only when CI is green.
- Run `ruff check .`, `ruff format .` and `python -m pytest -q` before pushing.
- Add or change dependencies with `uv add <package>`, and commit both `pyproject.toml` and `uv.lock`.
- Upgrade one package with `uv lock --upgrade-package <name>`, or all of them with `uv lock --upgrade`, then run the tests.
- Every behavior change comes with tests. For security-relevant code, check that the new test fails when the fix is removed.
- Never commit secrets. `.env` and `monitoring/metrics_token*` are ignored; check with `git check-ignore -v <file>` before creating a secret file.
- Update this README in the same pull request as the feature (see [Maintaining this README](#maintaining-this-readme)).

## Security design

- Phone numbers are validated in international format; OTPs are six random digits, hashed with an HMAC bound to the challenge and phone, expire after 5 minutes, and are single use.
- The JWT algorithm is fixed by the server, never read from the token, and issuer, audience and required claims are enforced.
- The caller's role is read from the database on every request, so role changes and deactivation take effect immediately.
- Passwords are Argon2id hashes with a 12-character minimum. Public login errors are identical for unknown users and wrong passwords.
- Ownership and jurisdiction are checked on the server for every incident and photo operation.
- Uploads are validated by decoding the image, never by filename or client content type, and are re-encoded without metadata before storage.
- The database port in `docker-compose.yml` is bound to `127.0.0.1`, and so are the Prometheus and Grafana ports.
- Logs record route templates, never raw URLs, query strings, request bodies, passwords, tokens or OTPs. Caller-supplied request IDs are validated before use.
- Unhandled errors and failed readiness checks return generic responses; details go only to the log.
- `/metrics` requires a bearer token outside development, compared in constant time. The token is read from a Git-ignored file by Prometheus and never appears in configuration committed to the repository.
- Secrets live in environment variables and are never committed. CI uses throwaway values that exist only inside the workflow.

## Known limitations

- **Photo GPS is client-supplied.** EXIF coordinates can be forged, so the 100 m check catches honest mistakes, not deliberate fraud.
- **Photos are stored on local disk** and there is no download endpoint yet. Use object storage before running more than one instance. On the Render free tier they are lost on every restart.
- **No audit log yet.** Admin access to reporter phone numbers is not recorded.
- **No status workflow beyond `DRAFT` to `REPORTED`.**
- **A lost refresh response looks like token reuse.** If the server rotates a token but the client never receives the reply, the retry revokes the session family and the user must sign in again.
- **Naive timestamps** (no timezone) in `incident_datetime` are accepted but cannot be checked against the clock.
- **No request body size limit in the app.** Set one at the reverse proxy.
- **No security headers or CORS configuration yet.**
- **The demo is not production.** It uses the console OTP provider and in-memory rate limiting, and there is no Dockerfile for the API, staging environment or backup plan.
- **Metrics are per process.** With several Uvicorn workers each would report its own numbers. Prometheus multiprocess mode would be needed.
- **Alerts are only a first version.** There is no Alertmanager, so nothing is delivered to a phone or inbox, and rules are evaluated only while Prometheus is running (currently on a developer machine). The first 5xx on a brand-new route/status series is not counted by the rate-based alerts, because Prometheus cannot see a counter go from 0 to 1 on a series it has just created.
- **No log search.** Logs are structured but only viewed through the hosting platform or a terminal.
- **No load test yet,** so capacity and the alert thresholds are unmeasured.

## Roadmap

1. Load testing and capacity planning: seed realistic data, run Locust scenarios in a resource-limited container, record one change per round in a results table, and tune pool sizes, workers, indexes and caching from what the dashboard shows.
2. Append-only audit log for logins, account changes, status changes and admin data access.
3. Incident status workflow with per-role transitions.
4. Object storage for photos with authorized, short-lived download links.
5. A real OTP provider (SMS) and Redis-backed rate limiting, so the app can run with `APP_ENV=production`.
6. Dockerfile for the API, staging environment and production deployment with managed PostgreSQL, backups and runbooks.
7. Security headers and CORS.
8. DSS integration using a transactional outbox with retries and signed payloads.
9. Alertmanager with a notification channel, log search (Loki or an ELK stack) and error tracking (Sentry).

## Change log

Newest first. Add a line for every merged feature or fix.

| Date | Change |
|---|---|
| 2026-11 | Prometheus alert rules (`AppDown`, `HighServerErrorRate`, `RepeatedServerErrors`, `HighLatency`) with `promtool` unit tests |
| 2026-11 | Prometheus and Grafana monitoring stack (Docker Compose profile), 15-panel dashboard, token-protected scraping of the Render demo |
| 2026-11 | Resource metrics: database pool, query time, new connections and worker threads; finer latency buckets |
| 2026-11 | Request metrics at `/metrics` (rate, errors, duration), with bounded labels and token protection |
| 2026-11 | Structured JSON logs, request IDs, liveness and readiness endpoints, database connect timeout |
| 2026-10 | Deployed a demo to Render's free tier |
| 2026-10 | Adopted `uv` with a committed lock file; Dependabot now watches Python packages |
| 2026-10 | Added GitHub Actions CI (lint, format check, migrations, tests on PostgreSQL) |
| 2026-10 | Auth hardening: `Role` enum, timing-safe staff login, rate limits on token endpoints, all-session revocation on credential change, connection pool settings |
| 2026-10 | Incident visibility and validation: drafts hidden from other officials, bounded inputs, exact-match admin filters, 422 responses no longer echo input, draft purge script |
| 2026-10 | Photo upload hardening: EXIF/GPS stripped from stored copies, pixel and total-size limits, upload route moved off the event loop |
| 2026-10 | Per-phone OTP throttle; a new OTP invalidates earlier ones |
| 2026-10 | Fixed `users.created_at` being evaluated once at import time (migration included) |
| 2026-10 | Startup validation of security settings; configurable rate-limit storage |
| 2026-10 | Declared runtime dependencies, removed unused user routes, bound PostgreSQL to localhost |
| 2026-10 | Initial backend: OTP and staff authentication, refresh tokens, incident reporting with photos, migrations |

## Maintaining this README

When a pull request changes behavior, update these sections in the same pull request:

- **What is implemented** and **API endpoints**: new or changed endpoints, roles and rules.
- **Configuration**: every new or changed setting, with its default. Also update `.env.example`.
- **Rate limiting**: new or changed limits.
- **Database and migrations**: new tables or migration steps others must run.
- **Observability**: new metrics, dashboard panels, alert rules or log fields.
- **Deployment**: changes to hosting settings or environment variables.
- **Known limitations** and **Roadmap**: remove what you finished, add what you learned.
- **Change log**: one line for the change.

Keep claims accurate. Describe only what the code does today, and move anything planned to the Roadmap.
