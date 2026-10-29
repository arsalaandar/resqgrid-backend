import pytest
from sqlalchemy.exc import IntegrityError

from app.core.security import create_access_token
from app.models.user import User


def auth_headers(user):
    token = create_access_token(user.id, token_version=user.token_version)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_user(db_session):
    user = User(
        phone="+919100000020",
        role="ADMIN",
        is_active=True,
        is_verified=True,
        must_change_password=False,
        token_version=0,
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def super_admin_user(db_session):
    user = User(
        phone="+919100000021",
        role="SUPER_ADMIN",
        is_active=True,
        is_verified=True,
        must_change_password=False,
        token_version=0,
    )
    db_session.add(user)
    db_session.flush()
    return user


def admin_payload(**overrides):
    payload = {
        "phone": "+919100000022",
        "password": "Strong-Test-Password-2026!",
        "designation": "Administrator",
        "department": "Disaster Management",
    }
    payload.update(overrides)
    return payload


def official_payload(**overrides):
    payload = {
        "phone": "+919100000023",
        "password": "Strong-Test-Password-2026!",
        "designation": "Field Officer",
        "department": "Disaster Management",
        "assigned_district": "Srinagar",
        "assigned_tehsil": "Srinagar North",
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_admin_cannot_create_another_admin(auth_client, admin_user):
    response = await auth_client.post(
        "/api/v1/admin/admins",
        headers=auth_headers(admin_user),
        json=admin_payload(),
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_super_admin_can_create_admin(auth_client, super_admin_user):
    response = await auth_client.post(
        "/api/v1/admin/admins",
        headers=auth_headers(super_admin_user),
        json=admin_payload(),
    )

    assert response.status_code == 201
    assert response.json()["role"] == "ADMIN"
    assert response.json()["created_by_id"] == super_admin_user.id
    assert response.json()["must_change_password"] is True
    assert "password_hash" not in response.json()


@pytest.mark.asyncio
async def test_admin_can_create_official(auth_client, admin_user):
    response = await auth_client.post(
        "/api/v1/admin/officials",
        headers=auth_headers(admin_user),
        json=official_payload(),
    )

    assert response.status_code == 201
    assert response.json()["role"] == "OFFICIAL"
    assert response.json()["assigned_district"] == "Srinagar"
    assert response.json()["assigned_tehsil"] == "Srinagar North"
    assert response.json()["created_by_id"] == admin_user.id
    assert response.json()["must_change_password"] is True
    assert "password_hash" not in response.json()


@pytest.mark.asyncio
async def test_super_admin_can_create_official(auth_client, super_admin_user):
    response = await auth_client.post(
        "/api/v1/admin/officials",
        headers=auth_headers(super_admin_user),
        json=official_payload(),
    )

    assert response.status_code == 201
    assert response.json()["role"] == "OFFICIAL"


@pytest.mark.asyncio
async def test_unauthenticated_cannot_create_official(auth_client):
    response = await auth_client.post(
        "/api/v1/admin/officials",
        json=official_payload(),
    )

    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_duplicate_admin_phone_is_rejected(auth_client, super_admin_user):
    payload = admin_payload()

    first = await auth_client.post(
        "/api/v1/admin/admins",
        headers=auth_headers(super_admin_user),
        json=payload,
    )
    assert first.status_code == 201

    second = await auth_client.post(
        "/api/v1/admin/admins",
        headers=auth_headers(super_admin_user),
        json=payload,
    )
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_invalid_phone_is_rejected(auth_client, super_admin_user):
    response = await auth_client.post(
        "/api/v1/admin/admins",
        headers=auth_headers(super_admin_user),
        json=admin_payload(phone="not-a-phone"),
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_short_password_is_rejected(auth_client, super_admin_user):
    response = await auth_client.post(
        "/api/v1/admin/admins",
        headers=auth_headers(super_admin_user),
        json=admin_payload(password="short"),
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_invalid_official_district_is_rejected(auth_client, admin_user):
    response = await auth_client.post(
        "/api/v1/admin/officials",
        headers=auth_headers(admin_user),
        json=official_payload(assigned_district="NotARealDistrict"),
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_tehsil_from_another_district_is_rejected(auth_client, admin_user):
    response = await auth_client.post(
        "/api/v1/admin/officials",
        headers=auth_headers(admin_user),
        json=official_payload(
            assigned_district="Srinagar",
            assigned_tehsil="Baramulla",
        ),
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_admin_and_super_admin_can_access_admin_check(
    auth_client, admin_user, super_admin_user
):
    admin_response = await auth_client.get(
        "/api/v1/admin/check-access",
        headers=auth_headers(admin_user),
    )
    super_admin_response = await auth_client.get(
        "/api/v1/admin/check-access",
        headers=auth_headers(super_admin_user),
    )

    assert admin_response.status_code == 200
    assert admin_response.json()["role"] == "ADMIN"
    assert super_admin_response.status_code == 200
    assert super_admin_response.json()["role"] == "SUPER_ADMIN"


@pytest.mark.asyncio
async def test_admin_incident_list_filters_and_paginates(
    auth_client,
    admin_user,
    db_session,
):
    # Use the existing admin fixture and authenticated test client.
    token = create_access_token(admin_user.id)

    response = await auth_client.get(
        "/api/v1/admin/incidents",
        params={
            "district": "Srinagar",
            "status": "DRAFT",
            "limit": 1,
            "offset": 0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200

    body = response.json()
    assert body["limit"] == 1
    assert body["offset"] == 0
    assert len(body["items"]) <= 1

    for item in body["items"]:
        assert item["district"] == "Srinagar"
        assert item["status"] == "DRAFT"


@pytest.mark.asyncio
async def test_create_admin_integrity_error_rolls_back(
    auth_client,
    super_admin_user,
    db_session,
    monkeypatch,
):
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

    monkeypatch.setattr(db_session, "commit", fail_commit)
    monkeypatch.setattr(db_session, "rollback", track_rollback)

    response = await auth_client.post(
        "/api/v1/admin/admins",
        headers=auth_headers(super_admin_user),
        json=admin_payload(),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "An account with this phone number already exists."
    )
    assert rollback_called is True


@pytest.mark.asyncio
async def test_create_official_integrity_error_rolls_back(
    auth_client,
    admin_user,
    db_session,
    monkeypatch,
):
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

    monkeypatch.setattr(db_session, "commit", fail_commit)
    monkeypatch.setattr(db_session, "rollback", track_rollback)

    response = await auth_client.post(
        "/api/v1/admin/officials",
        headers=auth_headers(admin_user),
        json=official_payload(),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "An account with this phone number already exists."
    )
    assert rollback_called is True
