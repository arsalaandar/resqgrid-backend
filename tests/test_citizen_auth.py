import httpx
import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.api.routes import auth as auth_routes
from app.core.security import decode_access_token
from app.db.dependencies import get_db
from app.main import app
from app.models.user import User

BASE_URL = "/api/v1/auth/citizen"


@pytest_asyncio.fixture
async def auth_client(db_session):
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


def create_user(
    db_session,
    phone,
    role="CITIZEN",
    is_active=True,
    is_verified=True,
):
    user = User(
        phone=phone,
        role=role,
        is_active=is_active,
        is_verified=is_verified,
        must_change_password=False,
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.mark.asyncio
async def test_request_otp_returns_generic_success(auth_client, monkeypatch):
    calls = []

    def fake_request_otp(db, phone):
        calls.append(phone)

    monkeypatch.setattr(
        auth_routes,
        "request_otp",
        fake_request_otp,
    )

    response = await auth_client.post(
        f"{BASE_URL}/request-otp",
        json={"phone": "+919876543210"},
    )

    assert response.status_code == 200
    assert response.json()["message"] == (
        "If the request can be processed, an OTP will be sent."
    )
    assert calls == ["+919876543210"]


@pytest.mark.asyncio
async def test_request_otp_hides_provider_error(auth_client, monkeypatch):
    def fail_request_otp(db, phone):
        raise RuntimeError("Internal provider details")

    monkeypatch.setattr(
        auth_routes,
        "request_otp",
        fail_request_otp,
    )

    response = await auth_client.post(
        f"{BASE_URL}/request-otp",
        json={"phone": "+919876543211"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == ("OTP service temporarily unavailable.")
    assert "Internal provider details" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"phone": "not-a-phone"},
        {"phone": "12345"},
        {"phone": "+919876543210", "code": "12345"},
        {"phone": "+919876543210", "code": "12AB56"},
    ],
)
async def test_auth_rejects_invalid_payloads(auth_client, payload):
    endpoint = (
        f"{BASE_URL}/request-otp" if "code" not in payload else f"{BASE_URL}/verify-otp"
    )

    response = await auth_client.post(endpoint, json=payload)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_invalid_otp_is_rejected(
    auth_client,
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(
        auth_routes,
        "verify_otp",
        lambda db, phone, code: False,
    )

    response = await auth_client.post(
        f"{BASE_URL}/verify-otp",
        json={"phone": "+919876543212", "code": "000000"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid or expired OTP."


@pytest.mark.asyncio
async def test_new_citizen_can_login_and_receives_jwt(
    auth_client,
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(
        auth_routes,
        "verify_otp",
        lambda db, phone, code: True,
    )

    phone = "+919876543213"

    response = await auth_client.post(
        f"{BASE_URL}/verify-otp",
        json={"phone": phone, "code": "123456"},
    )

    assert response.status_code == 200
    data = response.json()

    assert data["token_type"] == "bearer"
    assert data["role"] == "CITIZEN"
    assert data["expires_in"] > 0

    user = db_session.query(User).filter(User.phone == phone).one()

    assert data["user_id"] == user.id
    assert user.role == "CITIZEN"
    assert user.is_active is True
    assert user.is_verified is True

    claims = decode_access_token(data["access_token"])
    assert claims["sub"] == str(user.id)


@pytest.mark.asyncio
async def test_existing_citizen_can_login(
    auth_client,
    db_session,
    monkeypatch,
):
    phone = "+919876543214"
    user = create_user(db_session, phone)

    monkeypatch.setattr(
        auth_routes,
        "verify_otp",
        lambda db, phone, code: True,
    )

    response = await auth_client.post(
        f"{BASE_URL}/verify-otp",
        json={"phone": phone, "code": "123456"},
    )

    assert response.status_code == 200
    assert response.json()["user_id"] == user.id


@pytest.mark.asyncio
async def test_official_cannot_use_citizen_login(
    auth_client,
    db_session,
    monkeypatch,
):
    phone = "+919876543215"
    create_user(db_session, phone, role="OFFICIAL")

    monkeypatch.setattr(
        auth_routes,
        "verify_otp",
        lambda db, phone, code: True,
    )

    response = await auth_client.post(
        f"{BASE_URL}/verify-otp",
        json={"phone": phone, "code": "123456"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == ("This account cannot use citizen login.")


@pytest.mark.asyncio
async def test_inactive_citizen_cannot_login(
    auth_client,
    db_session,
    monkeypatch,
):
    phone = "+919876543216"
    create_user(db_session, phone, is_active=False)

    monkeypatch.setattr(
        auth_routes,
        "verify_otp",
        lambda db, phone, code: True,
    )

    response = await auth_client.post(
        f"{BASE_URL}/verify-otp",
        json={"phone": phone, "code": "123456"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "This account is inactive."


@pytest.mark.asyncio
async def test_unverified_citizen_is_verified_on_successful_login(
    auth_client,
    db_session,
    monkeypatch,
):
    phone = "+919876543217"
    user = create_user(db_session, phone, is_verified=False)

    monkeypatch.setattr(
        auth_routes,
        "verify_otp",
        lambda db, phone, code: True,
    )

    response = await auth_client.post(
        f"{BASE_URL}/verify-otp",
        json={"phone": phone, "code": "123456"},
    )

    assert response.status_code == 200

    db_session.refresh(user)
    assert user.is_verified is True


@pytest.mark.asyncio
async def test_unverified_citizen_database_failure_rolls_back(
    auth_client,
    db_session,
    monkeypatch,
):
    phone = "+919876543230"
    create_user(db_session, phone, is_verified=False)

    # Persist the setup account before simulating the failed update.
    db_session.commit()

    rollback_called = False
    original_rollback = db_session.rollback

    def fail_commit():
        raise SQLAlchemyError("simulated database failure")

    def track_rollback():
        nonlocal rollback_called
        rollback_called = True
        return original_rollback()

    monkeypatch.setattr(auth_routes, "verify_otp", lambda db, phone, code: True)
    monkeypatch.setattr(db_session, "commit", fail_commit)
    monkeypatch.setattr(db_session, "rollback", track_rollback)

    response = await auth_client.post(
        f"{BASE_URL}/verify-otp",
        json={"phone": phone, "code": "123456"},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Could not update the account."
    assert rollback_called is True

    # Query again after rollback; don't refresh a potentially detached instance.
    monkeypatch.undo()
    persisted_user = db_session.query(User).filter(User.phone == phone).one()
    assert persisted_user.is_verified is False


@pytest.mark.asyncio
async def test_account_creation_integrity_error_without_account_returns_conflict(
    auth_client,
    db_session,
    monkeypatch,
):
    phone = "+919876543231"
    rollback_called = False
    original_rollback = db_session.rollback

    def fail_commit():
        raise IntegrityError(
            "simulated insert failure",
            {},
            Exception("simulated constraint violation"),
        )

    def track_rollback():
        nonlocal rollback_called
        rollback_called = True
        return original_rollback()

    monkeypatch.setattr(auth_routes, "verify_otp", lambda db, phone, code: True)
    monkeypatch.setattr(db_session, "commit", fail_commit)
    monkeypatch.setattr(db_session, "rollback", track_rollback)

    response = await auth_client.post(
        f"{BASE_URL}/verify-otp",
        json={"phone": phone, "code": "123456"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Account creation conflict. Request a new OTP."
    )
    assert rollback_called is True
    assert db_session.query(User).filter(User.phone == phone).first() is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "is_active", "expected_status", "expected_detail"),
    [
        (
            "OFFICIAL",
            True,
            403,
            "This account cannot use citizen login.",
        ),
        (
            "CITIZEN",
            False,
            403,
            "This account is inactive.",
        ),
        ("CITIZEN", True, 200, None),
    ],
)
@pytest.mark.asyncio
async def test_account_creation_race_rechecks_existing_account(
    auth_client,
    db_session,
    monkeypatch,
    role,
    is_active,
    expected_status,
    expected_detail,
):
    phone = "+919876543232"

    original_commit = db_session.commit
    original_rollback = db_session.rollback
    conflict_simulated = False

    def simulate_concurrent_insert():
        nonlocal conflict_simulated

        if conflict_simulated:
            # Subsequent commits, including refresh-token persistence,
            # use the real database session behavior.
            return original_commit()

        conflict_simulated = True

        # Discard the route's pending new-citizen insert.
        original_rollback()

        # Simulate another request having created the account first.
        concurrent_user = User(
            phone=phone,
            role=role,
            is_active=is_active,
            is_verified=True,
            must_change_password=False,
        )
        db_session.add(concurrent_user)
        original_commit()

        # Tell the route its own account insert lost the race.
        raise IntegrityError(
            "simulated concurrent unique-key conflict",
            {},
            Exception("unique constraint violation"),
        )

    monkeypatch.setattr(
        auth_routes,
        "verify_otp",
        lambda db, phone, code: True,
    )
    monkeypatch.setattr(
        db_session,
        "commit",
        simulate_concurrent_insert,
    )

    response = await auth_client.post(
        f"{BASE_URL}/verify-otp",
        json={"phone": phone, "code": "123456"},
    )

    assert conflict_simulated is True
    assert response.status_code == expected_status

    # Verify that the competing account really exists in the database.
    account = db_session.query(User).filter(User.phone == phone).one()
    assert account.role == role
    assert account.is_active is is_active

    if expected_status == 403:
        assert response.json()["detail"] == expected_detail
    else:
        assert response.json()["role"] == "CITIZEN"
        assert response.json()["user_id"] == account.id
        assert response.json()["access_token"]
        assert response.json()["refresh_token"]
