"""Fill a LOCAL database with realistic fake data for load testing.

An empty database makes every query look fast, so load tests need rows to
search through. This script creates citizens, officials, admins and incidents
with a realistic spread: a few busy districts, a mix of categories, and
reports spread over the last year.

Usage (run from the project root, with the database already migrated):

    python -m scripts.seed_load_test_data --confirm
    python -m scripts.seed_load_test_data --incidents 500000 --confirm
    python -m scripts.seed_load_test_data --reset --confirm   # start again

It refuses to run against anything that is not a local database.
"""

import argparse
import random
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.incident_options import (
    DAMAGE_SITUATIONS,
    DISTRICT_TEHSILS,
    INCIDENT_CATEGORIES,
    INCIDENT_SEVERITY_LEVELS,
)
from app.core.passwords import hash_password
from app.core.roles import Role
from app.models.incident import Incident
from app.models.refresh_token import RefreshToken
from app.models.user import User

# Every seeded phone number starts with this, so seeded rows are easy to find
# and remove without touching real accounts.
SEED_PHONE_PREFIX = "+9199"

# One shared password for all seeded staff. It is a throwaway for local
# testing only and is printed by the script.
STAFF_PASSWORD = "LoadTest-Passw0rd-123"

# Where seeding is allowed. None means a local socket connection.
LOCAL_HOSTS = {"localhost", "127.0.0.1", "postgres", None}
SAFE_ENVIRONMENTS = {"development", "testing"}

BATCH_SIZE = 5_000


def check_target(database_url: str, app_env: str) -> None:
    """Refuse to seed anything that could be a shared or real database."""
    if app_env not in SAFE_ENVIRONMENTS:
        raise SystemExit(
            f"Refusing to seed: APP_ENV is '{app_env}'. "
            f"Seeding is allowed only in {sorted(SAFE_ENVIRONMENTS)}."
        )

    host = make_url(database_url).host

    if host not in LOCAL_HOSTS:
        raise SystemExit(
            f"Refusing to seed: the database host '{host}' is not local. "
            "This script only fills a database on your own machine."
        )


def phone_for(role_digit: int, number: int) -> str:
    """Build a valid, recognisable fake phone number (digit 0, 1 or 2 = role)."""
    return f"{SEED_PHONE_PREFIX}{role_digit}{number:07d}"


def seeded_users_exist(session: Session) -> bool:
    return (
        session.scalar(
            select(func.count(User.id)).where(User.phone.like(f"{SEED_PHONE_PREFIX}%"))
        )
        > 0
    )


def reset(session: Session) -> int:
    """Delete all seeded data. Real accounts are never touched."""
    seeded_ids = select(User.id).where(User.phone.like(f"{SEED_PHONE_PREFIX}%"))

    session.execute(delete(Incident).where(Incident.reporter_id.in_(seeded_ids)))
    session.execute(delete(RefreshToken).where(RefreshToken.user_id.in_(seeded_ids)))
    result = session.execute(
        delete(User).where(User.phone.like(f"{SEED_PHONE_PREFIX}%"))
    )
    session.commit()

    return result.rowcount


def seed(
    session: Session,
    *,
    citizens: int,
    officials: int,
    admins: int,
    incidents: int,
    seed_value: int = 42,
    progress=None,
) -> dict[str, int]:
    """Create the fake users and incidents. Returns how many of each."""
    if seeded_users_exist(session):
        raise SystemExit("Seed data already exists. Run again with --reset.")

    rng = random.Random(seed_value)
    now = datetime.now(UTC)
    say = progress or (lambda message: None)

    # --- Users -------------------------------------------------------------
    # Hashing is deliberately slow, so do it once and share the result.
    staff_hash = hash_password(STAFF_PASSWORD)

    jurisdictions = [
        (district, tehsil)
        for district, tehsils in DISTRICT_TEHSILS.items()
        for tehsil in tehsils
    ]

    user_rows = []

    for i in range(admins):
        user_rows.append(
            _user_row(phone_for(2, i), Role.ADMIN, staff_hash, designation="Admin")
        )

    for i in range(officials):
        district, tehsil = jurisdictions[i % len(jurisdictions)]
        user_rows.append(
            _user_row(
                phone_for(1, i),
                Role.OFFICIAL,
                staff_hash,
                designation="Field Official",
                department="Disaster Management",
                district=district,
                tehsil=tehsil,
            )
        )

    for i in range(citizens):
        user_rows.append(_user_row(phone_for(0, i), Role.CITIZEN, None))

    for start in range(0, len(user_rows), BATCH_SIZE):
        session.execute(insert(User), user_rows[start : start + BATCH_SIZE])
        session.commit()

    citizen_ids = list(
        session.scalars(
            select(User.id)
            .where(User.phone.like(f"{SEED_PHONE_PREFIX}0%"))
            .order_by(User.id)
        )
    )
    say(f"Created {len(user_rows):,} users")

    # --- Incidents ---------------------------------------------------------
    # A few districts are much busier than the rest, as in real data.
    weights = [rng.paretovariate(1.5) for _ in jurisdictions]
    created = 0

    while created < incidents:
        count = min(BATCH_SIZE, incidents - created)
        places = rng.choices(jurisdictions, weights=weights, k=count)
        rows = [
            _incident_row(rng, now, rng.choice(citizen_ids), district, tehsil)
            for district, tehsil in places
        ]
        session.execute(insert(Incident), rows)
        session.commit()
        created += count

        if created % (BATCH_SIZE * 10) == 0 or created == incidents:
            say(f"Created {created:,} of {incidents:,} incidents")

    return {
        "citizens": citizens,
        "officials": officials,
        "admins": admins,
        "incidents": incidents,
    }


def _user_row(
    phone: str,
    role: Role,
    password_hash: str | None,
    *,
    designation: str | None = None,
    department: str | None = None,
    district: str | None = None,
    tehsil: str | None = None,
) -> dict:
    return {
        "phone": phone,
        "password_hash": password_hash,
        "role": role.value,
        "designation": designation,
        "department": department,
        "assigned_district": district,
        "assigned_tehsil": tehsil,
        "must_change_password": False,
        "token_version": 0,
        "is_active": True,
        "is_verified": True,
    }


def _incident_row(
    rng: random.Random,
    now: datetime,
    reporter_id: int,
    district: str,
    tehsil: str,
) -> dict:
    category = rng.choice(INCIDENT_CATEGORIES)

    # Squaring a random number puts more reports in recent months.
    age_seconds = (rng.random() ** 2) * 365 * 24 * 3600
    created_at = now - timedelta(seconds=age_seconds)

    return {
        "reporter_id": reporter_id,
        "description": f"Seeded report: {category} near {tehsil}, {district}.",
        "latitude": rng.uniform(32.3, 34.9),
        "longitude": rng.uniform(73.9, 76.0),
        "status": "DRAFT" if rng.random() < 0.05 else "REPORTED",
        "created_at": created_at,
        "incident_category": category,
        "is_drill": rng.random() < 0.05,
        "incident_datetime": created_at - timedelta(minutes=rng.randint(5, 600)),
        "district": district,
        "tehsil": tehsil,
        "incident_location": f"Near the main road, {tehsil}",
        "incident_details": "Generated for load testing.",
        "village_or_ward": f"Ward {rng.randint(1, 30)}",
        "damage_situation": rng.choice(DAMAGE_SITUATIONS),
        "severity_level": rng.choice(INCIDENT_SEVERITY_LEVELS),
        "casualties": rng.choice([0, 0, 0, 0, 1, 2]),
        "people_missing": rng.choice([0, 0, 0, 1]),
        "minor_injuries": rng.randint(0, 5),
        "major_injuries": rng.choice([0, 0, 0, 1, 2]),
        "houses_completely_damaged": rng.choice([0, 0, 1, 2]),
        "houses_partially_damaged": rng.randint(0, 6),
        "roads_damaged_over_50_percent": rng.choice([0, 0, 1]),
        "additional_remarks": None,
        "voice_message_required": False,
        "medical_support_required": rng.random() < 0.1,
        "departmental_details": {},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--citizens", type=int, default=10_000)
    parser.add_argument("--officials", type=int, default=206)
    parser.add_argument("--admins", type=int, default=3)
    parser.add_argument("--incidents", type=int, default=200_000)
    parser.add_argument("--seed", type=int, default=42, help="repeatable randomness")
    parser.add_argument(
        "--reset", action="store_true", help="delete old seed data first"
    )
    parser.add_argument(
        "--confirm", action="store_true", help="required: acknowledge the target"
    )
    args = parser.parse_args()

    check_target(settings.DATABASE_URL, settings.APP_ENV)

    if not args.confirm:
        raise SystemExit(
            f"Would fill {make_url(settings.DATABASE_URL).render_as_string()} "
            "with fake data. Add --confirm to continue."
        )

    from app.db.database import SessionLocal, engine

    started = time.perf_counter()

    with SessionLocal() as session:
        if args.reset:
            print(f"Removed {reset(session):,} seeded users and their incidents")

        counts = seed(
            session,
            citizens=args.citizens,
            officials=args.officials,
            admins=args.admins,
            incidents=args.incidents,
            seed_value=args.seed,
            progress=print,
        )

    # Refresh the planner's statistics so query plans match the new data size.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("ANALYZE users"))
        conn.execute(text("ANALYZE incidents"))

    elapsed = time.perf_counter() - started
    print(f"\nDone in {elapsed:.1f} s: {counts}")
    print(f"Staff accounts share the password: {STAFF_PASSWORD}")
    print(f"Example official: {phone_for(1, 0)}   Example admin: {phone_for(2, 0)}")


if __name__ == "__main__":
    main()
