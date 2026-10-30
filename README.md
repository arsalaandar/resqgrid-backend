# ResQGrid

[![CI](https://github.com/arsalaandar/resqgrid-backend/actions/workflows/ci.yml/badge.svg)](https://github.com/arsalaandar/resqgrid-backend/actions/workflows/ci.yml)

ResQGrid is the backend for an emergency incident reporting platform. Citizens and field officials report incidents with a location and photographs, officials review what happens in their area, and admins manage staff accounts. A later milestone shares incidents with an external Decision Support System (DSS).

The API is built with FastAPI and PostgreSQL. A Flutter mobile client is planned; this repository contains only the backend.

> **Status:** authentication, role-based access control, incident reporting and photo upload are implemented and covered by automated tests that run against a real PostgreSQL database in CI. The service is **not deployed yet**. See [Known limitations](#known-limitations) and [Roadmap](#roadmap).

## Contents

- [Technology stack](#technology-stack)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [What is implemented](#what-is-implemented)
- [API endpoints](#api-endpoints)
- [Roles and permissions](#roles-and-permissions)
- [Incident lifecycle](#incident-lifecycle)
- [Rate limiting](#rate-limiting)
- [Database and migrations](#database-and-migrations)
- [Testing and CI](#testing-and-ci)
- [Scripts](#scripts)
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
| Packaging | `uv` with a committed `uv.lock` |
| Tests and lint | pytest, pytest-asyncio, httpx, Ruff |
| CI | GitHub Actions, Dependabot |

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
| `INCIDENT_PHOTO_STORAGE_DIR` | `storage/incident_photos` | Where photos are written |
| `INCIDENT_PHOTO_MIN_COUNT` / `_MAX_COUNT` | `3` / `10` | Photos required to report an incident |
| `INCIDENT_PHOTO_MAX_SIZE_BYTES` | `10 MiB` | Per-photo size limit |
| `INCIDENT_PHOTO_MAX_TOTAL_BYTES` | `60 MiB` | Combined size limit per upload |
| `INCIDENT_PHOTO_MAX_PIXELS` | `40,000,000` | Decoded pixel limit per photo |
| `INCIDENT_PHOTO_MAX_DISTANCE_METERS` | `100` | Maximum photo-to-incident GPS distance |

The app validates its settings at startup and refuses to start if:

- either secret is shorter than 32 characters, or the two secrets are identical;
- `JWT_SESSION_ABSOLUTE_EXPIRE_DAYS` is shorter than `JWT_REFRESH_TOKEN_EXPIRE_DAYS`;
- `APP_ENV` is `staging` or `production` while `OTP_PROVIDER` is `console` or `RATE_LIMIT_STORAGE_URI` is `memory://`.

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

## API endpoints

All paths are under `/api/v1` unless shown. "Any user" means any authenticated account that has no pending password change.

| Method | Path | Access | Purpose |
|---|---|---|---|
| GET | `/` (no prefix) | Public | Liveness message |
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

GitHub Actions (`.github/workflows/ci.yml`) runs lint, a formatting check, and the full test suite against a PostgreSQL service container on every push to `main` and every pull request. Dependabot proposes dependency updates weekly; CI tests each one before you merge it.

## Scripts

| Command | Purpose |
|---|---|
| `python -m scripts.bootstrap_super_admin` | Create the first `SUPER_ADMIN`. Prompts for the phone and password; nothing is stored in code or logs |
| `python -m scripts.purge_stale_drafts --days 7` | Delete `DRAFT` incidents older than the given number of days. Suitable for a daily scheduled job |

## Development workflow

- Work on a branch, open a pull request into `main`, and merge only when CI is green.
- Run `ruff check .`, `ruff format .` and `python -m pytest -q` before pushing.
- Add or change dependencies with `uv add <package>`, and commit both `pyproject.toml` and `uv.lock`.
- Upgrade one package with `uv lock --upgrade-package <name>`, or all of them with `uv lock --upgrade`, then run the tests.
- Every behavior change comes with tests. For security-relevant code, check that the new test fails when the fix is removed.
- Update this README in the same pull request as the feature (see [Maintaining this README](#maintaining-this-readme)).

## Security design

- Phone numbers are validated in international format; OTPs are six random digits, hashed with an HMAC bound to the challenge and phone, expire after 5 minutes, and are single use.
- The JWT algorithm is fixed by the server, never read from the token, and issuer, audience and required claims are enforced.
- The caller's role is read from the database on every request, so role changes and deactivation take effect immediately.
- Passwords are Argon2id hashes with a 12-character minimum. Public login errors are identical for unknown users and wrong passwords.
- Ownership and jurisdiction are checked on the server for every incident and photo operation.
- Uploads are validated by decoding the image, never by filename or client content type, and are re-encoded without metadata before storage.
- The database port in `docker-compose.yml` is bound to `127.0.0.1`.
- Secrets live in environment variables and are never committed. CI uses throwaway values that exist only inside the workflow.

## Known limitations

- **Photo GPS is client-supplied.** EXIF coordinates can be forged, so the 100 m check catches honest mistakes, not deliberate fraud.
- **Photos are stored on local disk** and there is no download endpoint yet. Use object storage before running more than one instance.
- **No audit log yet.** Admin access to reporter phone numbers is not recorded.
- **No status workflow beyond `DRAFT` to `REPORTED`.**
- **A lost refresh response looks like token reuse.** If the server rotates a token but the client never receives the reply, the retry revokes the session family and the user must sign in again.
- **Naive timestamps** (no timezone) in `incident_datetime` are accepted but cannot be checked against the clock.
- **No request body size limit in the app.** Set one at the reverse proxy.
- **No health endpoints, request IDs or structured logging yet.**
- **Not deployed.** There is no Dockerfile for the API, staging environment or production configuration yet.

## Roadmap

1. Health endpoints (`/health/live`, `/health/ready`), request IDs, structured logs, security headers and CORS.
2. Append-only audit log for logins, account changes, status changes and admin data access.
3. Incident status workflow with per-role transitions.
4. Object storage for photos with authorized, short-lived download links.
5. DSS integration using a transactional outbox with retries and signed payloads.
6. Metrics (Prometheus) and error tracking (Sentry).
7. Dockerfile, staging environment and production deployment with managed PostgreSQL, Redis, backups and runbooks.

## Change log

Newest first. Add a line for every merged feature or fix.

| Date | Change |
|---|---|
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
- **Known limitations** and **Roadmap**: remove what you finished, add what you learned.
- **Change log**: one line for the change.

Keep claims accurate. Describe only what the code does today, and move anything planned to the Roadmap.
