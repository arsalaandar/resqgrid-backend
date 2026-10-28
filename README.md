# ResQGrid

ResQGrid is a backend service for citizen incident reporting and coordination with an external Decision Support System (DSS). It is built with FastAPI and PostgreSQL. Authentication, role-based access control, incident reporting and photo upload are implemented and tested; DSS integration is the next milestone.

> **Project status:** the automated suite (246 tests at the time of writing) runs against a real PostgreSQL database. Check `pytest` output for the current count.

## Table of Contents

- [Technology Stack](#technology-stack)
- [What Is Implemented](#what-is-implemented)
- [Roles and Permissions](#roles-and-permissions)
- [Rate Limiting](#rate-limiting)
- [Configuration](#configuration)
- [Run the Project](#run-the-project)
- [Testing](#testing)
- [API Documentation](#api-documentation)
- [Known Limitations](#known-limitations)
- [Next Milestones](#next-milestones)
- [Security Notes](#security-notes)

## Technology Stack

| Area | Technology |
|---|---|
| API | FastAPI, Python 3.13 |
| Database | PostgreSQL (SQLAlchemy 2, Alembic) |
| Auth | JWT access tokens, opaque rotating refresh tokens |
| Passwords | `pwdlib` with Argon2id |
| Images | Pillow |
| Rate limiting | SlowAPI (in-memory in development, Redis in production) |
| Tests | pytest, pytest-asyncio, httpx |

Exact versions are pinned in `requirements.txt` (runtime) and `requirements-dev.txt` (adds test and lint tools).

## What Is Implemented

- **Citizen login** with phone number and OTP. OTP requests are throttled per phone number (cooldown plus hourly and daily caps), a newer OTP invalidates older ones, and codes are stored only as HMAC verifiers.
- **Staff login** (`SUPER_ADMIN`, `ADMIN`, `OFFICIAL`) with phone and password. Login does one password verification even for unknown numbers so timing does not reveal which accounts exist, and old password hashes are upgraded automatically.
- **Staff account management.** A `SUPER_ADMIN` creates admins, admins and super admins create officials with a district and tehsil, and new accounts must change their temporary password before using other endpoints. The first `SUPER_ADMIN` is created with `python -m scripts.bootstrap_super_admin`.
- **Tokens.** Short-lived access tokens carry a `token_version`; changing a password or deactivating an account invalidates them. Refresh tokens are hashed, rotated on every use, grouped into session families with an absolute lifetime, and reuse of a rotated token revokes the whole family. A credential change revokes all of the user's sessions.
- **Incident reporting.** Citizens, officials and admins create an incident as a `DRAFT`. It becomes `REPORTED` only when 3 to 10 valid photos are uploaded.
- **Photo validation.** Each photo is checked by real image content (JPEG, PNG, WEBP), size, pixel count and embedded GPS, which must be within 100 m of the incident. Stored copies are re-encoded **without EXIF/GPS metadata**.
- **Access control.** Citizens see only their own incidents. Officials see submitted incidents inside their district and tehsil, plus any draft they wrote themselves. Admins see all incidents through a filterable, paginated list.
- **Operations.** Alembic migrations, a script to purge abandoned drafts (`python -m scripts.purge_stale_drafts --days 7`), startup validation of security settings.

## Roles and Permissions

| Role | Can do |
|---|---|
| `CITIZEN` | Log in with OTP, report incidents, view own incidents |
| `OFFICIAL` | Staff login, report within own jurisdiction, view submitted incidents in own jurisdiction |
| `ADMIN` | Everything an official can, create officials, list all incidents |
| `SUPER_ADMIN` | Everything an admin can, create admins |

Roles are defined once in `app/core/roles.py`. Unknown role names passed to `require_roles` fail at startup.

## Rate Limiting

| Endpoint | Limit (per IP) |
|---|---:|
| `POST /api/v1/auth/citizen/request-otp` | 3 per minute |
| `POST /api/v1/auth/citizen/verify-otp` | 10 per minute |
| `POST /api/v1/auth/staff/login` | 5 per minute |
| `POST /api/v1/auth/staff/change-password` | 5 per minute |
| `POST /api/v1/auth/refresh` | 30 per minute |
| `POST /api/v1/auth/logout` | 30 per minute |

Violations return `429`. OTP sends are additionally limited **per phone number** inside the OTP service (`OTP_RESEND_COOLDOWN_SECONDS`, `OTP_MAX_REQUESTS_PER_HOUR`, `OTP_MAX_REQUESTS_PER_DAY`), and a throttled request gets the same response as a successful one.

In staging and production the app refuses to start with in-memory limiter storage. Set `RATE_LIMIT_STORAGE_URI` to a shared store such as `redis://host:6379/0`. Run Uvicorn with `--proxy-headers --forwarded-allow-ips=<proxy IP>` behind a reverse proxy so client IPs are correct.

## Configuration

Copy `.env.example` to `.env` and fill in real values. `.env` is ignored by Git. The app validates its settings at startup and will not start if:

- `JWT_SECRET_KEY` or `OTP_HMAC_SECRET` is shorter than 32 characters, or the two are identical;
- `APP_ENV` is `staging` or `production` while `OTP_PROVIDER=console` or the rate-limit storage is `memory://`.

Generate secrets with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Run the Project

```powershell
cd C:\Users\arsal\Desktop\dss
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
docker compose up -d          # PostgreSQL, bound to 127.0.0.1 only
alembic upgrade head
python -m scripts.bootstrap_super_admin
python -m uvicorn app.main:app --reload
```

## Testing

Tests run against a dedicated PostgreSQL database named `resqgrid_test`; a safety check in `tests/conftest.py` refuses any other database.

1. Create the database and migrate it:

   ```powershell
   $env:DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@localhost:5432/resqgrid_test"
   alembic upgrade head
   ```

2. Put `TEST_DATABASE_URL` in `.env` (`pytest-dotenv` loads it) and run:

   ```powershell
   python -m pytest -q
   ```

Re-run `alembic upgrade head` against the test database after pulling new migrations. Rate-limit counters are reset before every test.

## API Documentation

With the server running: Swagger UI at `/docs`, ReDoc at `/redoc`, schema at `/openapi.json`.

## Known Limitations

- **Photo GPS is client-supplied.** EXIF coordinates can be forged, so the 100 m check catches honest mistakes, not deliberate fraud.
- **Photos are stored on local disk** (`INCIDENT_PHOTO_STORAGE_DIR`) and there is no download endpoint yet. Use object storage before running more than one instance.
- **No audit log yet.** Admin access to reporter phone numbers is not recorded.
- **No incident status workflow beyond `DRAFT` to `REPORTED`.**
- **A lost refresh response looks like token reuse.** If the server rotates a token but the client never receives the reply, the retry revokes the session family and the user must log in again.
- Naive (timezone-less) `incident_datetime` values are accepted but cannot be checked against the clock.
- Request body size is not capped by the app; set a limit at the reverse proxy.

## Next Milestones

1. CI (tests against PostgreSQL, lint, dependency audit, `alembic check`).
2. Audit logging, structured logs with request IDs, health endpoints.
3. Incident status workflow with per-role transitions.
4. Object storage and signed URLs for photos.
5. DSS integration using a transactional outbox, retries and signed payloads.
6. Production deployment: secrets manager, TLS, backups, monitoring, runbooks.

## Security Notes

- Never store plaintext passwords or commit real secrets.
- Use HTTPS in production and keep test and production databases separate.
- Authorize every request on the server and enforce ownership checks to prevent IDOR.
- Do not trust filenames or client content types for uploads.
- Validation errors never echo submitted values back to the client.
- Use a real OTP provider in production; the console provider only works when `APP_ENV=development`.
