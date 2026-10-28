import pytest
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from sqlalchemy import select

from app.core import passwords
from app.core.config import settings
from app.core.passwords import hash_password, verify_password
from app.core.permissions import require_roles
from app.core.roles import ADMIN_ROLES, STAFF_ROLES, Role
from app.core.security import create_access_token
from app.db.database import engine
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.services.refresh_tokens import create_refresh_session

PASSWORD = "Initial-Password-123!"
LOGIN_URL = "/api/v1/auth/staff/login"


def make_user(db_session, phone, role="OFFICIAL", password=PASSWORD, **extra):
    user = User(
        phone=phone,
        role=role,
        password_hash=hash_password(password) if password else None,
        is_active=extra.pop("is_active", True),
        is_verified=True,
        must_change_password=False,
        **extra,
    )
    db_session.add(user)
    db_session.flush()
    return user


def headers(user):
    token = create_access_token(user.id, token_version=user.token_version)
    return {"Authorization": f"Bearer {token}"}


# -------------------------------------------------------------------- roles


def test_plain_database_strings_match_role_sets():
    assert "OFFICIAL" in STAFF_ROLES
    assert "SUPER_ADMIN" in ADMIN_ROLES
    assert "CITIZEN" not in STAFF_ROLES
    assert "OFFICIAL" not in ADMIN_ROLES


def test_require_roles_rejects_unknown_role_names_at_definition_time():
    with pytest.raises(ValueError):
        require_roles("ADMN")


def test_require_roles_accepts_enum_members_and_strings():
    require_roles(Role.ADMIN, "super_admin")


# ------------------------------------------------------------- login timing


class SpyHash:
    """Counts password verifications while delegating to the real hasher."""

    def __init__(self, real):
        self._real = real
        self.calls = 0

    def verify_and_update(self, password, hash_value):
        self.calls += 1
        return self._real.verify_and_update(password, hash_value)

    def __getattr__(self, name):
        return getattr(self._real, name)


@pytest.fixture
def spy(monkeypatch):
    spy = SpyHash(passwords._password_hash)
    monkeypatch.setattr(passwords, "_password_hash", spy)
    return spy


@pytest.mark.asyncio
async def test_unknown_phone_still_performs_one_verification(auth_client, spy):
    response = await auth_client.post(
        LOGIN_URL, json={"phone": "+919100000901", "password": PASSWORD}
    )

    assert response.status_code == 401
    assert spy.calls == 1


@pytest.mark.asyncio
async def test_account_without_password_still_performs_one_verification(
    auth_client, db_session, spy
):
    user = make_user(db_session, "+919100000902", password=None)
    spy.calls = 0

    response = await auth_client.post(
        LOGIN_URL, json={"phone": user.phone, "password": PASSWORD}
    )

    assert response.status_code == 401
    assert spy.calls == 1


@pytest.mark.asyncio
async def test_existing_account_performs_exactly_one_verification(
    auth_client, db_session, spy
):
    user = make_user(db_session, "+919100000903")
    spy.calls = 0

    wrong = await auth_client.post(
        LOGIN_URL, json={"phone": user.phone, "password": "Wrong-Password-1!"}
    )
    right = await auth_client.post(
        LOGIN_URL, json={"phone": user.phone, "password": PASSWORD}
    )

    assert wrong.status_code == 401
    assert right.status_code == 200
    assert spy.calls == 2


@pytest.mark.asyncio
async def test_citizen_with_correct_password_is_still_rejected(
    auth_client, db_session
):
    user = make_user(db_session, "+919100000904", role="CITIZEN")

    response = await auth_client.post(
        LOGIN_URL, json={"phone": user.phone, "password": PASSWORD}
    )

    assert response.status_code == 401


def test_dummy_hash_is_a_valid_hash():
    # If the dummy were malformed, verification would fail fast and the
    # timing protection would silently stop working.
    valid, _ = passwords._password_hash.verify_and_update(
        "timing-equalizer-password", passwords._DUMMY_HASH
    )
    assert valid is True


@pytest.mark.asyncio
async def test_sixth_staff_login_attempt_is_rate_limited(auth_client):
    statuses = []
    for _ in range(6):
        response = await auth_client.post(
            LOGIN_URL, json={"phone": "+919100000905", "password": PASSWORD}
        )
        statuses.append(response.status_code)

    assert statuses == [401, 401, 401, 401, 401, 429]


# ------------------------------------------------------------------ rehash


@pytest.mark.asyncio
async def test_login_upgrades_a_hash_with_outdated_parameters(
    auth_client, db_session
):
    weak_hasher = PasswordHash(
        (Argon2Hasher(time_cost=1, memory_cost=8, parallelism=1),)
    )
    old_hash = weak_hasher.hash(PASSWORD)
    user = make_user(db_session, "+919100000906", password=None)
    user.password_hash = old_hash
    db_session.flush()

    response = await auth_client.post(
        LOGIN_URL, json={"phone": user.phone, "password": PASSWORD}
    )

    assert response.status_code == 200
    db_session.refresh(user)
    assert user.password_hash != old_hash
    assert verify_password(PASSWORD, user.password_hash)

    # Already-current hashes are left alone.
    current_hash = user.password_hash
    again = await auth_client.post(
        LOGIN_URL, json={"phone": user.phone, "password": PASSWORD}
    )
    assert again.status_code == 200
    db_session.refresh(user)
    assert user.password_hash == current_hash


# -------------------------------------------------- refresh-token revocation


def active_tokens(db_session, user):
    db_session.expire_all()
    return db_session.scalars(
        select(RefreshToken).where(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked_at.is_(None),
        )
    ).all()


@pytest.mark.asyncio
async def test_credential_change_revokes_every_session_of_that_user(
    auth_client, db_session
):
    user = make_user(db_session, "+919100000907", role="CITIZEN")
    other = make_user(db_session, "+919100000908", role="CITIZEN")
    phone_token, _ = create_refresh_session(db=db_session, user=user)
    create_refresh_session(db=db_session, user=user)  # second device
    other_token, _ = create_refresh_session(db=db_session, user=other)

    user.token_version += 1
    db_session.flush()

    response = await auth_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": phone_token}
    )

    assert response.status_code == 401
    assert active_tokens(db_session, user) == []
    # Another user's session is unaffected.
    assert len(active_tokens(db_session, other)) == 1
    assert other_token


@pytest.mark.asyncio
async def test_deactivation_revokes_every_session_of_that_user(
    auth_client, db_session
):
    user = make_user(db_session, "+919100000909", role="CITIZEN")
    first, _ = create_refresh_session(db=db_session, user=user)
    create_refresh_session(db=db_session, user=user)

    user.is_active = False
    db_session.flush()

    response = await auth_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": first}
    )

    assert response.status_code == 401
    assert active_tokens(db_session, user) == []


# -------------------------------------------------------------- rate limits


@pytest.mark.asyncio
async def test_refresh_endpoint_is_rate_limited(auth_client):
    statuses = []
    for _ in range(31):
        response = await auth_client.post(
            "/api/v1/auth/refresh", json={"refresh_token": "not-a-token"}
        )
        statuses.append(response.status_code)

    assert statuses[:30] == [401] * 30
    assert statuses[30] == 429


@pytest.mark.asyncio
async def test_logout_endpoint_is_rate_limited(auth_client):
    statuses = []
    for _ in range(31):
        response = await auth_client.post(
            "/api/v1/auth/logout", json={"refresh_token": "not-a-token"}
        )
        statuses.append(response.status_code)

    assert statuses[:30] == [200] * 30
    assert statuses[30] == 429


@pytest.mark.asyncio
async def test_change_password_endpoint_is_rate_limited(
    auth_client, db_session
):
    user = make_user(db_session, "+919100000910")
    statuses = []

    for _ in range(6):
        response = await auth_client.post(
            "/api/v1/auth/staff/change-password",
            headers=headers(user),
            json={
                "current_password": "Wrong-Password-123!",
                "new_password": "Replacement-Password-456!",
            },
        )
        statuses.append(response.status_code)

    assert statuses == [400, 400, 400, 400, 400, 429]


# ----------------------------------------------------------------- database


def test_engine_uses_a_configured_pool_with_pre_ping():
    assert engine.pool.size() == settings.DB_POOL_SIZE
    assert getattr(engine.pool, "_pre_ping", None) is True
