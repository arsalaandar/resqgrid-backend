import pytest
from sqlalchemy import func, select

from app.core.incident_options import DISTRICT_TEHSILS
from app.core.passwords import verify_password
from app.core.roles import Role
from app.models.incident import Incident
from app.models.user import User
from scripts.seed_load_test_data import (
    SEED_PHONE_PREFIX,
    STAFF_PASSWORD,
    check_target,
    reset,
    seed,
)

SMALL = {"citizens": 20, "officials": 5, "admins": 2, "incidents": 300}


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:p@localhost:5432/resqgrid",
        "postgresql+psycopg://u:p@127.0.0.1:5432/resqgrid",
        "postgresql+psycopg://u:p@postgres:5432/resqgrid",
        "postgresql+psycopg://u@/resqgrid?host=/var/run/postgresql",
    ],
)
def test_local_databases_are_allowed(url):
    check_target(url, "development")


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:p@dpg-abc123.oregon-postgres.render.com/resqgrid",
        "postgresql+psycopg://u:p@10.0.0.5:5432/resqgrid",
    ],
)
def test_remote_databases_are_refused(url):
    with pytest.raises(SystemExit, match="not local"):
        check_target(url, "development")


@pytest.mark.parametrize("env", ["staging", "production"])
def test_serious_environments_are_refused(env):
    with pytest.raises(SystemExit, match="Refusing to seed"):
        check_target("postgresql+psycopg://u:p@localhost/resqgrid", env)


def test_seed_creates_the_requested_rows(db_session):
    seed(db_session, **SMALL)

    def count_role(role):
        return db_session.scalar(
            select(func.count(User.id)).where(
                User.phone.like(f"{SEED_PHONE_PREFIX}%"), User.role == role
            )
        )

    assert count_role(Role.CITIZEN) == 20
    assert count_role(Role.OFFICIAL) == 5
    assert count_role(Role.ADMIN) == 2
    assert db_session.scalar(select(func.count(Incident.id))) == 300


def test_seeded_staff_can_log_in_with_the_shared_password(db_session):
    seed(db_session, **SMALL)

    official = db_session.scalar(select(User).where(User.role == Role.OFFICIAL))

    assert verify_password(STAFF_PASSWORD, official.password_hash)
    assert official.is_active
    assert not official.must_change_password


def test_every_place_and_status_is_valid(db_session):
    seed(db_session, **SMALL)

    pairs = db_session.execute(select(Incident.district, Incident.tehsil)).all()
    statuses = set(db_session.scalars(select(Incident.status)))

    assert all(tehsil in DISTRICT_TEHSILS[district] for district, tehsil in pairs)
    assert statuses <= {"REPORTED", "DRAFT"}


def test_same_seed_gives_the_same_data(db_session):
    seed(db_session, **SMALL, seed_value=7)
    first = list(
        db_session.execute(
            select(Incident.district, Incident.incident_category).order_by(Incident.id)
        )
    )
    reset(db_session)

    seed(db_session, **SMALL, seed_value=7)
    second = list(
        db_session.execute(
            select(Incident.district, Incident.incident_category).order_by(Incident.id)
        )
    )

    assert first == second


def test_seeding_twice_without_a_reset_is_refused(db_session):
    seed(db_session, **SMALL)

    with pytest.raises(SystemExit, match="already exists"):
        seed(db_session, **SMALL)


def test_reset_removes_only_seeded_data(db_session):
    real_user = User(phone="+14155550123", role=Role.CITIZEN)
    db_session.add(real_user)
    db_session.commit()

    seed(db_session, **SMALL)
    removed = reset(db_session)

    assert removed == 27
    assert db_session.scalar(select(func.count(Incident.id))) == 0
    assert db_session.scalar(select(User.id).where(User.phone == "+14155550123"))
