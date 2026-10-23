import httpx
import pytest
import pytest_asyncio
from sqlalchemy.exc import SQLAlchemyError

from app.core.passwords import hash_password, verify_password
from app.core.security import create_access_token
from app.db.dependencies import get_db
from app.main import app
from app.models.user import User

BASE_URL = "/api/v1/auth/staff"


@pytest_asyncio.fixture
async def staff_client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


def create_staff(
    db_session,
    phone="+919876543210",
    role="OFFICIAL",
    password="Initial-Password-123!",
    is_active=True,
    must_change_password=False,
):
    user = User(
        phone=phone,
        role=role,
        password_hash=hash_password(password),
        is_active=is_active,
        is_verified=True,
        must_change_password=must_change_password,
    )
    db_session.add(user)
    db_session.flush()
    return user


def auth_headers(user):
    token = create_access_token(user_id=user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role",
    ["SUPER_ADMIN", "ADMIN", "OFFICIAL"],
)
async def test_staff_login_success(staff_client, db_session, role):
    password = "Initial-Password-123!"
    user = create_staff(
        db_session,
        role=role,
        password=password,
        must_change_password=True,
    )

    response = await staff_client.post(
        f"{BASE_URL}/login",
        json={"phone": user.phone, "password": password},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == user.id
    assert data["role"] == role
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0
    assert data["must_change_password"] is True
    assert data["access_token"]


@pytest.mark.asyncio
async def test_staff_login_unknown_phone_returns_generic_error(staff_client):
    response = await staff_client.post(
        f"{BASE_URL}/login",
        json={
            "phone": "+919999999999",
            "password": "Wrong-Password-123!",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == ("Invalid phone number or password.")
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.asyncio
async def test_staff_login_wrong_password_returns_generic_error(
    staff_client,
    db_session,
):
    user = create_staff(db_session)

    response = await staff_client.post(
        f"{BASE_URL}/login",
        json={
            "phone": user.phone,
            "password": "Wrong-Password-123!",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == ("Invalid phone number or password.")


@pytest.mark.asyncio
async def test_citizen_cannot_use_staff_login(staff_client, db_session):
    create_staff(
        db_session,
        role="CITIZEN",
        phone="+919876543211",
    )

    response = await staff_client.post(
        f"{BASE_URL}/login",
        json={
            "phone": "+919876543211",
            "password": "Initial-Password-123!",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == ("Invalid phone number or password.")


@pytest.mark.asyncio
async def test_inactive_staff_cannot_log_in(staff_client, db_session):
    user = create_staff(db_session, is_active=False)

    response = await staff_client.post(
        f"{BASE_URL}/login",
        json={
            "phone": user.phone,
            "password": "Initial-Password-123!",
        },
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_staff_login_rejects_extra_fields(staff_client):
    response = await staff_client.post(
        f"{BASE_URL}/login",
        json={
            "phone": "+919876543210",
            "password": "Initial-Password-123!",
            "role": "SUPER_ADMIN",
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_password_change_success(staff_client, db_session):
    old_password = "Initial-Password-123!"
    new_password = "Replacement-Password-456!"
    user = create_staff(
        db_session,
        password=old_password,
        must_change_password=True,
    )

    response = await staff_client.post(
        f"{BASE_URL}/change-password",
        headers=auth_headers(user),
        json={
            "current_password": old_password,
            "new_password": new_password,
        },
    )

    assert response.status_code == 200
    assert response.json()["must_change_password"] is False
    assert user.must_change_password is False
    assert verify_password(new_password, user.password_hash)
    assert not verify_password(old_password, user.password_hash)


@pytest.mark.asyncio
async def test_password_change_rejects_wrong_current_password(
    staff_client,
    db_session,
):
    user = create_staff(db_session)

    response = await staff_client.post(
        f"{BASE_URL}/change-password",
        headers=auth_headers(user),
        json={
            "current_password": "Wrong-Password-123!",
            "new_password": "Replacement-Password-456!",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Current password is incorrect."


@pytest.mark.asyncio
async def test_password_change_rejects_same_password(
    staff_client,
    db_session,
):
    password = "Initial-Password-123!"
    user = create_staff(db_session, password=password)

    response = await staff_client.post(
        f"{BASE_URL}/change-password",
        headers=auth_headers(user),
        json={
            "current_password": password,
            "new_password": password,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Choose a password different from your current password."
    )


@pytest.mark.asyncio
async def test_password_change_rejects_citizen(staff_client, db_session):
    user = create_staff(db_session, role="CITIZEN")

    response = await staff_client.post(
        f"{BASE_URL}/change-password",
        headers=auth_headers(user),
        json={
            "current_password": "Initial-Password-123!",
            "new_password": "Replacement-Password-456!",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == ("This endpoint is for staff accounts only.")


@pytest.mark.asyncio
async def test_password_change_requires_authentication(staff_client):
    response = await staff_client.post(
        f"{BASE_URL}/change-password",
        json={
            "current_password": "Initial-Password-123!",
            "new_password": "Replacement-Password-456!",
        },
    )

    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "new_password",
    ["short", "            "],
)
async def test_password_change_rejects_invalid_new_password(
    staff_client,
    db_session,
    new_password,
):
    user = create_staff(db_session)

    response = await staff_client.post(
        f"{BASE_URL}/change-password",
        headers=auth_headers(user),
        json={
            "current_password": "Initial-Password-123!",
            "new_password": new_password,
        },
    )

    assert response.status_code == 422


def test_password_hashing_does_not_store_plaintext():
    password = "A-Strong-Password-123!"

    stored_hash = hash_password(password)

    assert stored_hash != password
    assert verify_password(password, stored_hash)
    assert not verify_password("Incorrect-Password-123!", stored_hash)


@pytest.mark.parametrize(
    "password",
    ["", "short", "            "],
)
def test_hash_password_rejects_short_or_blank_passwords(password):
    with pytest.raises(ValueError):
        hash_password(password)


def test_verify_password_handles_empty_or_invalid_hash():
    assert verify_password("", "some-hash") is False
    assert verify_password("some-password", "") is False
    assert verify_password("some-password", "not-a-valid-hash") is False


@pytest.mark.asyncio
async def test_password_change_rolls_back_on_database_failure(
    staff_client,
    db_session,
    monkeypatch,
):
    old_password = "Initial-Password-123!"
    user = create_staff(
        db_session,
        password=old_password,
        must_change_password=True,
    )

    original_rollback = db_session.rollback
    rollback_called = False

    def fail_commit():
        raise SQLAlchemyError("Simulated database failure")

    def track_rollback():
        nonlocal rollback_called
        rollback_called = True
        original_rollback()

    monkeypatch.setattr(db_session, "commit", fail_commit)
    monkeypatch.setattr(db_session, "rollback", track_rollback)

    response = await staff_client.post(
        f"{BASE_URL}/change-password",
        headers=auth_headers(user),
        json={
            "current_password": old_password,
            "new_password": "Replacement-Password-456!",
        },
    )

    assert response.status_code == 500
    assert response.json()["detail"] == ("Password change failed. Please try again.")
    assert rollback_called


@pytest.mark.asyncio
async def test_password_change_invalidates_existing_access_token(
    staff_client,
    db_session,
):
    user = create_staff(db_session)
    old_token_headers = auth_headers(user)

    # First password change should succeed.
    first_change = await staff_client.post(
        "/api/v1/auth/staff/change-password",
        headers=old_token_headers,
        json={
            "current_password": "Initial-Password-123!",
            "new_password": "Changed-Password-456!",
        },
    )

    assert first_change.status_code == 200

    # Reuse the original token after the password change.
    second_change = await staff_client.post(
        "/api/v1/auth/staff/change-password",
        headers=old_token_headers,
        json={
            "current_password": "Changed-Password-456!",
            "new_password": "Another-Password-789!",
        },
    )

    # Desired security behavior: the old token must no longer work.
    assert second_change.status_code == 401
