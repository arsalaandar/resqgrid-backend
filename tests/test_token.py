
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.services.refresh_tokens import create_refresh_session

BASE_URL = "/api/v1/auth"


def create_test_user(db_session, phone="+919876540001"):
    user = User(
        phone=phone,
        role="CITIZEN",
        is_active=True,
        is_verified=True,
        must_change_password=False,
    )
    db_session.add(user)
    db_session.flush()
    return user


def create_test_session(db_session, user):
    raw_token, _ = create_refresh_session(db=db_session, user=user)
    return raw_token


@pytest.mark.asyncio
async def test_refresh_rotates_token(auth_client, db_session):
    user = create_test_user(db_session)
    old_token = create_test_session(db_session, user)

    response = await auth_client.post(
        f"{BASE_URL}/refresh",
        json={"refresh_token": old_token},
    )

    assert response.status_code == 200
    data = response.json()

    assert data["access_token"]
    assert data["refresh_token"]
    assert data["refresh_token"] != old_token
    assert data["user_id"] == user.id
    assert data["role"] == "CITIZEN"
    assert data["expires_in"] > 0
    assert data["refresh_expires_in"] > 0

    old_record = db_session.scalar(
        select(RefreshToken).where(
            RefreshToken.user_id == user.id,
            RefreshToken.replaced_by_id.is_not(None),
        )
    )
    assert old_record is not None
    assert old_record.revoked_at is not None


@pytest.mark.asyncio
async def test_reusing_rotated_token_is_rejected(
    auth_client,
    db_session,
):
    user = create_test_user(db_session, phone="+919876540002")
    old_token = create_test_session(db_session, user)

    first_response = await auth_client.post(
        f"{BASE_URL}/refresh",
        json={"refresh_token": old_token},
    )
    assert first_response.status_code == 200

    current_token = first_response.json()["refresh_token"]

    reuse_response = await auth_client.post(
        f"{BASE_URL}/refresh",
        json={"refresh_token": old_token},
    )
    assert reuse_response.status_code == 401

    current_record = db_session.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash.is_not(None),
            RefreshToken.revoked_at.is_(None),
            RefreshToken.user_id == user.id,
        )
    )
    assert current_record is None

    current_token_response = await auth_client.post(
        f"{BASE_URL}/refresh",
        json={"refresh_token": current_token},
    )
    assert current_token_response.status_code == 401


@pytest.mark.asyncio
async def test_invalid_refresh_token_is_rejected(auth_client):
    response = await auth_client.post(
        f"{BASE_URL}/refresh",
        json={"refresh_token": "not-a-valid-refresh-token"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == (
        "Invalid or expired refresh token."
    )


@pytest.mark.asyncio
async def test_logout_revokes_refresh_session(auth_client, db_session):
    user = create_test_user(db_session, phone="+919876540003")
    refresh_token = create_test_session(db_session, user)

    response = await auth_client.post(
        f"{BASE_URL}/logout",
        json={"refresh_token": refresh_token},
    )

    assert response.status_code == 200
    assert response.json()["message"] == "Logout successful."

    refresh_response = await auth_client.post(
        f"{BASE_URL}/refresh",
        json={"refresh_token": refresh_token},
    )
    assert refresh_response.status_code == 401


@pytest.mark.asyncio
async def test_expired_refresh_token_is_rejected(
    auth_client,
    db_session,
):
    user = create_test_user(db_session, phone="+919876540004")
    raw_token = create_test_session(db_session, user)

    record = db_session.scalar(
        select(RefreshToken).where(
            RefreshToken.user_id == user.id
        )
    )
    assert record is not None

    record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.flush()

    response = await auth_client.post(
        f"{BASE_URL}/refresh",
        json={"refresh_token": raw_token},
    )

    assert response.status_code == 401

@pytest.mark.asyncio
async def test_inactive_user_cannot_refresh(auth_client, db_session):
    user = create_test_user(db_session, phone="+919876540005")
    raw_token = create_test_session(db_session, user)

    user.is_active = False
    db_session.flush()

    response = await auth_client.post(
        f"{BASE_URL}/refresh",
        json={"refresh_token": raw_token},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired refresh token."

    record = db_session.scalar(
        select(RefreshToken).where(RefreshToken.user_id == user.id)
    )
    assert record is not None
    assert record.revoked_at is not None


@pytest.mark.asyncio
async def test_old_token_version_cannot_refresh(auth_client, db_session):
    user = create_test_user(db_session, phone="+919876540006")
    raw_token = create_test_session(db_session, user)

    user.token_version += 1
    db_session.flush()

    response = await auth_client.post(
        f"{BASE_URL}/refresh",
        json={"refresh_token": raw_token},
    )

    assert response.status_code == 401

    record = db_session.scalar(
        select(RefreshToken).where(RefreshToken.user_id == user.id)
    )
    assert record is not None
    assert record.revoked_at is not None


@pytest.mark.asyncio
async def test_logout_unknown_token_is_idempotent(auth_client):
    response = await auth_client.post(
        f"{BASE_URL}/logout",
        json={"refresh_token": "unknown-refresh-token"},
    )

    assert response.status_code == 200
    assert response.json()["message"] == "Logout successful."


@pytest.mark.asyncio
async def test_refresh_rejects_missing_token_field(auth_client):
    response = await auth_client.post(
        f"{BASE_URL}/refresh",
        json={},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_logout_revokes_entire_refresh_family(
    auth_client,
    db_session,
):
    user = create_test_user(db_session, phone="+919876540007")
    first_token = create_test_session(db_session, user)

    first_response = await auth_client.post(
        f"{BASE_URL}/refresh",
        json={"refresh_token": first_token},
    )
    assert first_response.status_code == 200

    second_token = first_response.json()["refresh_token"]

    logout_response = await auth_client.post(
        f"{BASE_URL}/logout",
        json={"refresh_token": second_token},
    )
    assert logout_response.status_code == 200

    refresh_response = await auth_client.post(
        f"{BASE_URL}/refresh",
        json={"refresh_token": second_token},
    )
    assert refresh_response.status_code == 401

    records = db_session.scalars(
        select(RefreshToken).where(RefreshToken.user_id == user.id)
    ).all()

    assert len(records) == 2
    assert all(record.revoked_at is not None for record in records)
