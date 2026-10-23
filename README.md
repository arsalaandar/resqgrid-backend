# ResQGrid

ResQGrid is a backend service being developed to support citizen incident reporting and coordination with an external Decision Support System (DSS). The backend is built with FastAPI and PostgreSQL, with authentication and role-based access control forming the foundation.

> **Project status:** Authentication, token handling, database migrations, and rate limiting have been implemented and tested. The most recent reported test run passed **169 tests**. Incident-reporting endpoints are the planned next milestone; they should not be considered implemented unless they have since been added to the codebase.

## Table of Contents

- [Project Goals](#project-goals)
- [Technology Stack](#technology-stack)
- [Implemented So Far](#implemented-so-far)
- [Authentication and Authorization](#authentication-and-authorization)
- [Rate Limiting](#rate-limiting)
- [Database and Migrations](#database-and-migrations)
- [Testing](#testing)
- [Development Environment](#development-environment)
- [Environment Configuration](#environment-configuration)
- [Run the Project](#run-the-project)
- [API Documentation](#api-documentation)
- [Next Milestones](#next-milestones)
- [Security Notes](#security-notes)

## Project Goals

The broader ResQGrid system is intended to support:

- Citizen authentication using phone number and OTP verification.
- Staff/official authentication.
- Secure, role-aware API access.
- Citizen incident reporting with location information and photographs.
- Official review and management of reported incidents.
- Integration with a separate DSS application so relevant teams can respond.

The mobile client is planned to use Flutter. This repository's current focus is the Python backend.

## Technology Stack

| Area | Technology |
|---|---|
| Backend API | FastAPI |
| Language | Python |
| Database | PostgreSQL |
| ORM | SQLAlchemy |
| Schema migrations | Alembic |
| Authentication | JWT-based access/refresh token flow |
| Password hashing | `pwdlib` with Argon2id, as configured in the project |
| Rate limiting | SlowAPI |
| Development database | PostgreSQL, run locally through Docker |
| Testing | pytest |
| Client planned for the broader system | Flutter |

Check the project's dependency files and configuration for the exact installed versions.

## Implemented So Far

### 1. FastAPI application structure

- An application package under `app/`, including core configuration and API modules.
- API routers for citizen authentication and staff authentication.
- Application-level integration of the authentication routers.
- A custom OpenAPI adjustment was included in the application setup.

### 2. Citizen authentication

The citizen authentication workflow includes OTP-related endpoints and account handling.

- Request a one-time password (OTP).
- Verify an OTP.
- Create or retrieve the citizen account as part of the authentication flow.
- Handle account state and verification fields.
- Use a console OTP provider for local development/testing where configured.

The development console provider is intended for testing; a real deployment requires an appropriate OTP delivery provider and secure configuration.

### 3. Staff authentication

- A staff login endpoint.
- Password verification for staff credentials.
- Account-active checks before allowing login.
- A password-change endpoint.
- A distinct staff authentication route so citizen credentials cannot simply be treated as staff credentials.

### 4. Authentication tokens and authorization

The backend has JWT authentication and token verification in place.

- Configurable JWT secret and algorithm settings.
- Authenticated-user dependency for protected endpoints.
- Role-aware user model with roles discussed/implemented for `CITIZEN`, `OFFICIAL`, and `ADMIN`.
- Active and verified account fields.
- Password hashes are stored instead of plaintext passwords.

Protected endpoints require a valid token in the request's `Authorization` header, normally using the Bearer scheme.

### 5. Rate limiting

SlowAPI has been integrated into the application to reduce repeated authentication attempts.

| Endpoint | Configured limit |
|---|---:|
| `POST /api/v1/auth/citizen/request-otp` | 3 requests per minute |
| `POST /api/v1/auth/citizen/verify-otp` | 10 requests per minute |
| `POST /api/v1/auth/staff/login` | 5 requests per minute |

Rate-limit violations are handled as HTTP `429 Too Many Requests`.

The current IP-based limiter is a baseline protection. For production, consider shared Redis storage for multi-worker deployments, trusted-proxy configuration where applicable, and additional limits keyed by phone number to reduce OTP abuse.

### 6. Database and migrations

- PostgreSQL is used as the relational database.
- SQLAlchemy is used for database models and sessions.
- Alembic is used to generate and apply schema migrations.
- The users table has included fields such as `id`, `phone`, `email`, `password_hash`, `role`, `is_active`, `is_verified`, and `created_at`.
- PostgreSQL enum/migration issues were encountered during development and addressed as part of the migration work.

The exact current schema should always be confirmed from the models and the latest Alembic migrations in the repository.

### 7. Testing

- pytest is used for automated tests.
- Tests cover authentication and token behavior, among other existing application checks.
- A separate PostgreSQL test database, `resqgrid_test`, has been configured for tests.
- The most recent test run reported **169 passed** after resolving test setup and rate-limit interference.

Use a separate test database. Do not point tests at a production database or a development database containing data you need to preserve.

## Development Environment

The development environment discussed so far is:

- Windows
- PowerShell
- Project directory: `C:\Users\arsal\Desktop\dss`
- Python virtual environment: `venv`
- PostgreSQL running locally through Docker
- PostgreSQL container previously named `resqgrid-postgres`

Paths, container names, database names, and credentials may differ on another machine.

## Environment Configuration

Keep secrets and connection strings in environment variables or a local `.env` file that is excluded from version control.

Typical settings may include:

- Database connection URL.
- JWT signing secret and algorithm.
- OTP provider selection.
- OTP HMAC secret.
- OTP time-to-live and maximum verification attempts.
- Test database URL.

Example variable names discussed in development:

```dotenv
JWT_SECRET_KEY=replace-with-a-long-random-secret
OTP_PROVIDER=console
OTP_HMAC_SECRET=replace-with-a-separate-random-secret
OTP_TTL_SECONDS=300
OTP_MAX_ATTEMPTS=5
```

This is an illustrative example, not a complete `.env` file. Use the exact variable names expected by the current project configuration. Do not commit real secrets, passwords, tokens, or production connection strings to Git.

### PowerShell: configure the test database

Set the test URL in the current PowerShell session using your own local database credentials:

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://YOUR_USER:YOUR_PASSWORD@localhost:5432/resqgrid_test"
```

Replace the placeholders with the actual local PostgreSQL credentials. Keep this pointed at the dedicated test database.

## Run the Project

From the repository root:

```powershell
cd C:\Users\arsal\Desktop\dss
.\venv\Scripts\Activate.ps1
```

Install dependencies using the repository's dependency file. For example, if the project uses `requirements-dev.txt`:

```powershell
python -m pip install -r requirements-dev.txt
```

Start the application using the actual import path and app object in `app/main.py`. A common command, **only if the app object is `app` in `app.main`**, is:

```powershell
python -m uvicorn app.main:app --reload
```

If the project uses a different app object or launch configuration, follow the repository's current setup.

## API Documentation

When the server is running, FastAPI commonly exposes:

- Swagger UI: `/docs`
- ReDoc: `/redoc`
- OpenAPI schema: `/openapi.json`

Open these paths on the local server to inspect the registered routes and request/response schemas.

## Next Milestones

These are planned follow-up tasks, not claims that they are already implemented:

1. **Incident reporting API**
   - Create an incident.
   - Retrieve incidents and individual incident details.
   - Restrict citizens to their own records.
   - Allow authorized officials to access the incidents they are permitted to manage.
2. **Incident status workflow**
   - Define allowed statuses and authorized transitions.
3. **Photo uploads**
   - Validate file type and size.
   - Store uploads safely and associate them with incidents.
4. **Location data**
   - Validate latitude/longitude and persist incident coordinates.
5. **Audit logging**
   - Record security-sensitive actions and important status changes.
6. **DSS integration**
   - Define a secure API contract for sharing incident information with the DSS.
7. **Production hardening**
   - Shared rate-limit storage, deployment configuration, logging, monitoring, backups, and operational checks.

## Security Notes

- Never store plaintext passwords.
- Never commit real secrets or credentials.
- Use HTTPS in production.
- Keep test and production databases separate.
- Validate and authorize every request on the server; hiding a client-side control is not authorization.
- Enforce ownership checks to prevent insecure direct object reference (IDOR) vulnerabilities.
- Restrict uploads by size and allowed content; do not trust the filename or client-supplied content type alone.
- Configure trusted proxy headers carefully before relying on client IP addresses for rate limiting.
- Use a production OTP provider instead of exposing console OTPs.
- Configure shared rate-limit storage when deploying multiple workers or instances.

## Project Status Summary

**Completed / implemented:** foundational FastAPI backend, citizen OTP authentication flow, staff login, JWT-based authentication, role/account fields, PostgreSQL/SQLAlchemy integration, Alembic migrations, SlowAPI endpoint limits, and automated tests.

**Last reported test result:** `169 passed`.

**Next planned milestone:** build the incident reporting API and its permission model.
