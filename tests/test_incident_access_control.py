from datetime import UTC, datetime
from io import BytesIO

import httpx
import pytest
import pytest_asyncio
from PIL import Image

from app.core.security import create_access_token
from app.db.dependencies import get_db
from app.main import app
from app.models.incident import Incident
from app.models.incident_photo import IncidentPhoto
from app.models.user import User
from app.services.photo_gps import distance_meters


@pytest_asyncio.fixture
async def api_client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = httpx.ASGITransport(app=app)

    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def citizen(db_session):
    user = User(
        phone="9100000001",
        role="CITIZEN",
        is_active=True,
        is_verified=True,
        must_change_password=False,
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def another_citizen(db_session):
    user = User(
        phone="9100000002",
        role="CITIZEN",
        is_active=True,
        is_verified=True,
        must_change_password=False,
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def citizen_incident(db_session, citizen):
    incident = Incident(
        reporter_id=citizen.id,
        description="Flood water has entered the residential area.",
        latitude=34.0837,
        longitude=74.7973,
        district="Srinagar",
        tehsil="Srinagar",
        status="DRAFT",
        departmental_details={},
    )
    db_session.add(incident)
    db_session.flush()
    return incident

@pytest.fixture
def official_with_valid_jurisdiction(db_session):
    user = User(
        phone="9100000013",
        role="OFFICIAL",
        is_active=True,
        is_verified=True,
        must_change_password=False,
        assigned_district="Srinagar",
        assigned_tehsil="Srinagar North",
    )
    db_session.add(user)
    db_session.flush()
    return user

def _headers_for(user):
    token = create_access_token(
        user.id,
        token_version=user.token_version,
    )
    return {"Authorization": f"Bearer {token}"}


def _make_user(db_session, phone, role, **overrides):
    user = User(
        phone=phone,
        role=role,
        is_active=True,
        is_verified=True,
        must_change_password=False,
        token_version=0,
        **overrides,
    )
    db_session.add(user)
    db_session.flush()
    return user

@pytest.mark.asyncio
async def test_incident_requires_authentication(api_client):
    response = await api_client.get("/api/v1/incidents/1")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_incident_rejects_invalid_token(api_client):
    response = await api_client.get(
        "/api/v1/incidents/1",
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_citizen_can_view_own_incident(api_client, citizen, citizen_incident):
    token = create_access_token(citizen.id)

    response = await api_client.get(
        f"/api/v1/incidents/{citizen_incident.id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == citizen_incident.id
    assert response.json()["reporter_id"] == citizen.id


@pytest.mark.asyncio
async def test_citizen_cannot_view_another_citizens_incident(
    api_client, another_citizen, citizen_incident
):
    token = create_access_token(another_citizen.id)

    response = await api_client.get(
        f"/api/v1/incidents/{citizen_incident.id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    # The API should not reveal another citizen's incident.
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_inactive_user_is_rejected(api_client, db_session):
    user = User(
        phone="9100000003",
        role="CITIZEN",
        is_active=False,
        is_verified=True,
        must_change_password=False,
    )
    db_session.add(user)
    db_session.flush()

    token = create_access_token(user.id)

    response = await api_client.get(
        "/api/v1/incidents/1",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_user_must_change_password_before_access(api_client, db_session):
    user = User(
        phone="9100000004",
        role="OFFICIAL",
        is_active=True,
        is_verified=True,
        must_change_password=True,
    )
    db_session.add(user)
    db_session.flush()

    token = create_access_token(user.id)

    response = await api_client.get(
        "/api/v1/incidents/1",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


@pytest.fixture
def official(db_session):
    user = User(
        phone="9100000005",
        role="OFFICIAL",
        is_active=True,
        is_verified=True,
        must_change_password=False,
        assigned_district="Srinagar",
        assigned_tehsil="Srinagar",
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def outside_jurisdiction_incident(db_session, another_citizen):
    incident = Incident(
        reporter_id=another_citizen.id,
        description="Flood water has damaged a road outside the assigned area.",
        latitude=34.2090,
        longitude=74.3420,
        district="Baramulla",
        tehsil="Baramulla",
        status="REPORTED",
        departmental_details={},
    )
    db_session.add(incident)
    db_session.flush()
    return incident


@pytest.mark.asyncio
async def test_official_can_view_incident_in_assigned_jurisdiction(
    api_client, db_session, official, citizen_incident
):
    # Officials only see incidents that have actually been reported.
    citizen_incident.status = "REPORTED"
    db_session.flush()
    token = create_access_token(official.id)

    response = await api_client.get(
        f"/api/v1/incidents/{citizen_incident.id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == citizen_incident.id


@pytest.mark.asyncio
async def test_official_cannot_view_incident_outside_jurisdiction(
    api_client, official, outside_jurisdiction_incident
):
    token = create_access_token(official.id)

    response = await api_client.get(
        f"/api/v1/incidents/{outside_jurisdiction_incident.id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_official_assigned_endpoint_returns_only_own_jurisdiction(
    api_client,
    db_session,
    official,
    citizen_incident,
    outside_jurisdiction_incident,
):
    citizen_incident.status = "REPORTED"
    db_session.flush()
    token = create_access_token(official.id)

    response = await api_client.get(
        "/api/v1/incidents/assigned",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200

    incident_ids = {item["id"] for item in response.json()}

    assert citizen_incident.id in incident_ids
    assert outside_jurisdiction_incident.id not in incident_ids


@pytest.mark.asyncio
async def test_official_without_jurisdiction_is_denied(api_client, db_session):
    user = User(
        phone="9100000006",
        role="OFFICIAL",
        is_active=True,
        is_verified=True,
        must_change_password=False,
        assigned_district=None,
        assigned_tehsil=None,
    )
    db_session.add(user)
    db_session.flush()

    token = create_access_token(user.id)

    response = await api_client.get(
        "/api/v1/incidents/assigned",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_citizen_cannot_access_assigned_incidents(api_client, citizen):
    token = create_access_token(citizen.id)

    response = await api_client.get(
        "/api/v1/incidents/assigned",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_my_incidents_rejects_zero_limit(api_client, citizen):
    token = create_access_token(citizen.id)

    response = await api_client.get(
        "/api/v1/incidents/my?limit=0",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_my_incidents_rejects_limit_above_100(api_client, citizen):
    token = create_access_token(citizen.id)

    response = await api_client.get(
        "/api/v1/incidents/my?limit=101",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_my_incidents_rejects_negative_offset(api_client, citizen):
    token = create_access_token(citizen.id)

    response = await api_client.get(
        "/api/v1/incidents/my?offset=-1",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_nonexistent_incident_returns_404(api_client, citizen):
    token = create_access_token(citizen.id)

    response = await api_client.get(
        "/api/v1/incidents/999999999",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_wildcard_characters_do_not_expand_official_access(
    api_client,
    db_session,
    citizen,
    outside_jurisdiction_incident,
):
    official = User(
        phone="9100000007",
        role="OFFICIAL",
        is_active=True,
        is_verified=True,
        must_change_password=False,
        assigned_district="%",
        assigned_tehsil="%",
    )
    db_session.add(official)
    db_session.flush()

    token = create_access_token(official.id)

    response = await api_client.get(
        f"/api/v1/incidents/{outside_jurisdiction_incident.id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404

    response = await api_client.get(
        "/api/v1/incidents/assigned",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_photo_upload_rejects_too_few_files(api_client, citizen):
    token = create_access_token(citizen.id)

    files = [
        ("files", ("photo1.jpg", b"test", "image/jpeg")),
        ("files", ("photo2.jpg", b"test", "image/jpeg")),
    ]

    response = await api_client.post(
        "/api/v1/incidents/1/photos",
        headers={"Authorization": f"Bearer {token}"},
        files=files,
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_citizen_cannot_upload_photos_to_another_citizens_incident(
    api_client, another_citizen, citizen_incident
):
    token = create_access_token(another_citizen.id)

    files = [("files", (f"photo{i}.jpg", b"test", "image/jpeg")) for i in range(3)]

    response = await api_client.post(
        f"/api/v1/incidents/{citizen_incident.id}/photos",
        headers={"Authorization": f"Bearer {token}"},
        files=files,
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_photo_upload_rejects_invalid_image_content(
    api_client,
    citizen,
):
    token = create_access_token(citizen.id)

    response = await api_client.post(
        "/api/v1/incidents/1/photos",
        headers={"Authorization": f"Bearer {token}"},
        files=[
            ("files", (f"photo{i}.jpg", b"not-an-image", "image/jpeg"))
            for i in range(3)
        ],
    )

    assert response.status_code == 404 or response.status_code == 422


@pytest.mark.asyncio
async def test_photo_upload_rejects_unsupported_image_format(
    api_client, citizen, citizen_incident
):
    image_buffer = BytesIO()

    Image.new("RGB", (10, 10), color="white").save(image_buffer, format="BMP")

    image_bytes = image_buffer.getvalue()
    token = create_access_token(citizen.id)

    response = await api_client.post(
        f"/api/v1/incidents/{citizen_incident.id}/photos",
        headers={"Authorization": f"Bearer {token}"},
        files=[
            (
                "files",
                (f"photo{i}.bmp", image_bytes, "image/bmp"),
            )
            for i in range(3)
        ],
    )

    assert response.status_code == 415
    assert response.json()["detail"] == ("Only JPEG, PNG and WEBP photos are allowed.")


@pytest.mark.asyncio
async def test_photo_upload_rejects_oversized_file(
    api_client, citizen, citizen_incident
):
    token = create_access_token(citizen.id)
    oversized_content = b"x" * (10 * 1024 * 1024 + 1)

    response = await api_client.post(
        f"/api/v1/incidents/{citizen_incident.id}/photos",
        headers={"Authorization": f"Bearer {token}"},
        files=[
            ("files", ("large.jpg", oversized_content, "image/jpeg")),
            ("files", ("photo2.jpg", b"placeholder", "image/jpeg")),
            ("files", ("photo3.jpg", b"placeholder", "image/jpeg")),
        ],
    )

    assert response.status_code == 413
    assert response.json()["detail"] == ("Each photo must be 10 MB or smaller.")


@pytest.mark.asyncio
async def test_photo_upload_rejects_image_without_gps(
    api_client, citizen, citizen_incident
):
    image_buffer = BytesIO()
    Image.new("RGB", (10, 10), color="white").save(image_buffer, format="JPEG")
    image_bytes = image_buffer.getvalue()

    token = create_access_token(citizen.id)

    response = await api_client.post(
        f"/api/v1/incidents/{citizen_incident.id}/photos",
        headers={"Authorization": f"Bearer {token}"},
        files=[
            ("files", (f"photo{i}.jpg", image_bytes, "image/jpeg")) for i in range(3)
        ],
    )

    assert response.status_code == 422
    assert "GPS coordinates" in response.json()["detail"]


@pytest.mark.asyncio
async def test_failed_photo_upload_keeps_incident_in_draft(
    api_client, db_session, citizen, citizen_incident
):
    incident_id = citizen_incident.id
    token = create_access_token(citizen.id)

    before = db_session.get(Incident, incident_id)
    assert before is not None
    assert before.status == "DRAFT"

    # Preserve fixture setup within the outer test transaction.
    db_session.commit()

    response = await api_client.post(
        f"/api/v1/incidents/{incident_id}/photos",
        headers={"Authorization": f"Bearer {token}"},
        files=[
            ("files", (f"photo{i}.jpg", b"not-an-image", "image/jpeg"))
            for i in range(3)
        ],
    )

    assert response.status_code == 422

    after = db_session.get(Incident, incident_id)
    assert after is not None
    assert after.status == "DRAFT"


@pytest.mark.asyncio
async def test_failed_upload_cleans_up_previously_written_photos(
    api_client,
    db_session,
    citizen,
    citizen_incident,
    monkeypatch,
    tmp_path,
):
    from app.services import incident_photo as photo_service

    incident_id = citizen_incident.id
    token = create_access_token(citizen.id)

    # Use a temporary directory so this test cannot touch real uploads.
    monkeypatch.setattr(
        photo_service.settings,
        "INCIDENT_PHOTO_STORAGE_DIR",
        str(tmp_path),
    )

    # The first image will pass GPS validation.
    # The second image is deliberately invalid.
    monkeypatch.setattr(
        photo_service,
        "extract_photo_gps",
        lambda content: (
            citizen_incident.latitude,
            citizen_incident.longitude,
        ),
    )

    image_buffer = BytesIO()
    Image.new("RGB", (10, 10), color="white").save(image_buffer, format="JPEG")
    valid_jpeg = image_buffer.getvalue()

    # Keep the fixture data safe from the service's rollback.
    db_session.commit()

    response = await api_client.post(
        f"/api/v1/incidents/{incident_id}/photos",
        headers={"Authorization": f"Bearer {token}"},
        files=[
            ("files", ("first.jpg", valid_jpeg, "image/jpeg")),
            ("files", ("second.jpg", b"not-an-image", "image/jpeg")),
            ("files", ("third.jpg", valid_jpeg, "image/jpeg")),
        ],
    )

    assert response.status_code == 422

    # No files from the failed upload should remain on disk.
    assert list(tmp_path.iterdir()) == []

    # No photo records should have been saved.
    photo_count = (
        db_session.query(IncidentPhoto)
        .filter(IncidentPhoto.incident_id == incident_id)
        .count()
    )
    assert photo_count == 0

    # The incident should remain a draft.
    incident = db_session.get(Incident, incident_id)
    assert incident is not None
    assert incident.status == "DRAFT"


@pytest.mark.asyncio
async def test_photo_cleanup_failure_is_logged(
    api_client,
    db_session,
    citizen,
    citizen_incident,
    monkeypatch,
    tmp_path,
    caplog,
):
    import logging
    from io import BytesIO
    from pathlib import Path

    from PIL import Image

    from app.core.security import create_access_token
    from app.models.incident import Incident
    from app.models.incident_photo import IncidentPhoto
    from app.services import incident_photo as photo_service

    incident_id = citizen_incident.id
    token = create_access_token(citizen.id)

    monkeypatch.setattr(
        photo_service.settings,
        "INCIDENT_PHOTO_STORAGE_DIR",
        str(tmp_path),
    )
    monkeypatch.setattr(
        photo_service,
        "extract_photo_gps",
        lambda content: (
            citizen_incident.latitude,
            citizen_incident.longitude,
        ),
    )

    image_buffer = BytesIO()
    Image.new("RGB", (20, 20), "blue").save(image_buffer, format="JPEG")
    valid_jpeg = image_buffer.getvalue()

    # Keep fixture rows safe from the service's rollback.
    db_session.commit()

    original_unlink = Path.unlink

    def fail_unlink(self, *args, **kwargs):
        if self.parent == tmp_path:
            raise OSError("Simulated cleanup failure")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_unlink)

    with caplog.at_level(logging.ERROR, logger=photo_service.__name__):
        response = await api_client.post(
            f"/api/v1/incidents/{incident_id}/photos",
            headers={"Authorization": f"Bearer {token}"},
            files=[
                ("files", ("first.jpg", valid_jpeg, "image/jpeg")),
                ("files", ("second.jpg", b"invalid-image", "image/jpeg")),
                ("files", ("third.jpg", valid_jpeg, "image/jpeg")),
            ],
        )

    assert response.status_code == 422
    assert "Could not clean up a rejected photo." in caplog.text

    incident = db_session.get(Incident, incident_id)
    assert incident is not None
    assert incident.status == "DRAFT"

    photo_count = (
        db_session.query(IncidentPhoto)
        .filter(IncidentPhoto.incident_id == incident_id)
        .count()
    )
    assert photo_count == 0

    # Restore unlink before cleaning the deliberately retained test file.
    monkeypatch.setattr(Path, "unlink", original_unlink)
    for path in tmp_path.iterdir():
        path.unlink()


def test_distance_meters_returns_zero_for_same_coordinates():
    assert distance_meters(34.0837, 74.7973, 34.0837, 74.7973) == 0


def test_distance_meters_rejects_invalid_coordinates():
    with pytest.raises(ValueError):
        distance_meters(91, 74.7973, 34.0837, 74.7973)


def valid_incident_payload(**overrides):
    payload = {
        "incident_category": "Flood",
        "is_drill": False,
        "incident_datetime": datetime.now(UTC).isoformat(),
        "district": "Srinagar",
        "tehsil": "Srinagar North",
        "incident_location": "Residential area",
        "description": "Flood water has entered the residential area.",
        "incident_details": "Water level is rising near houses.",
        "village_or_ward": "Ward 1",
        "latitude": 34.0837,
        "longitude": 74.7973,
        "damage_situation": "Moderate",
        "severity_level": "L1",
        "additional_remarks": "Immediate assessment required.",
        "departmental_details": {},
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_admin_can_create_incident(api_client, db_session):
    admin = User(
        phone="9100000010",
        role="ADMIN",
        is_active=True,
        is_verified=True,
        must_change_password=False,
    )
    db_session.add(admin)
    db_session.flush()

    token = create_access_token(admin.id)

    response = await api_client.post(
        "/api/v1/incidents",
        headers={"Authorization": f"Bearer {token}"},
        json=valid_incident_payload(),
    )

    assert response.status_code == 201
    assert response.json()["reporter_id"] == admin.id
    assert response.json()["status"] == "DRAFT"


@pytest.mark.asyncio
async def test_super_admin_can_create_incident(api_client, db_session):
    super_admin = User(
        phone="9100000011",
        role="SUPER_ADMIN",
        is_active=True,
        is_verified=True,
        must_change_password=False,
    )
    db_session.add(super_admin)
    db_session.flush()

    token = create_access_token(super_admin.id)

    response = await api_client.post(
        "/api/v1/incidents",
        headers={"Authorization": f"Bearer {token}"},
        json=valid_incident_payload(),
    )

    assert response.status_code == 201
    assert response.json()["reporter_id"] == super_admin.id
    assert response.json()["status"] == "DRAFT"


@pytest.mark.asyncio
async def test_citizen_can_create_incident_as_draft(api_client, citizen):
    token = create_access_token(citizen.id)

    response = await api_client.post(
        "/api/v1/incidents",
        headers={"Authorization": f"Bearer {token}"},
        json=valid_incident_payload(),
    )

    assert response.status_code == 201
    assert response.json()["reporter_id"] == citizen.id
    assert response.json()["status"] == "DRAFT"


@pytest.mark.asyncio
async def test_official_cannot_create_incident_outside_jurisdiction(
    api_client, official
):
    token = create_access_token(official.id)

    response = await api_client.post(
        "/api/v1/incidents",
        headers={"Authorization": f"Bearer {token}"},
        json=valid_incident_payload(
            district="Baramulla",
            tehsil="Baramulla",
        ),
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_official_without_jurisdiction_cannot_create_incident(
    api_client, db_session
):
    official = User(
        phone="9100000012",
        role="OFFICIAL",
        is_active=True,
        is_verified=True,
        must_change_password=False,
        assigned_district=None,
        assigned_tehsil=None,
    )
    db_session.add(official)
    db_session.flush()

    token = create_access_token(official.id)

    response = await api_client.post(
        "/api/v1/incidents",
        headers={"Authorization": f"Bearer {token}"},
        json=valid_incident_payload(),
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_official_can_create_incident_within_jurisdiction(
    api_client, official_with_valid_jurisdiction
):
    official = official_with_valid_jurisdiction
    token = create_access_token(official.id)

    response = await api_client.post(
        "/api/v1/incidents",
        headers={"Authorization": f"Bearer {token}"},
        json=valid_incident_payload(
            district="Srinagar",
            tehsil="Srinagar North",
        ),
    )

    assert response.status_code == 201
    assert response.json()["reporter_id"] == official.id
    assert response.json()["status"] == "DRAFT"

@pytest.mark.asyncio
async def test_three_valid_photos_report_incident(
    api_client,
    db_session,
    citizen,
    citizen_incident,
    monkeypatch,
    tmp_path,
):
    from app.services import incident_photo as photo_service

    incident_id = citizen_incident.id

    monkeypatch.setattr(
        photo_service.settings,
        "INCIDENT_PHOTO_STORAGE_DIR",
        str(tmp_path),
    )

    # Simulate valid GPS metadata at the incident's coordinates.
    monkeypatch.setattr(
        photo_service,
        "extract_photo_gps",
        lambda content: (
            citizen_incident.latitude,
            citizen_incident.longitude,
        ),
    )

    image_buffer = BytesIO()
    Image.new("RGB", (10, 10), color="white").save(
        image_buffer,
        format="JPEG",
    )
    valid_jpeg = image_buffer.getvalue()

    token = create_access_token(
        citizen.id,
        token_version=citizen.token_version,
    )

    # Keep fixture data safe from the service's rollback behavior.
    db_session.commit()

    response = await api_client.post(
        f"/api/v1/incidents/{incident_id}/photos",
        headers={"Authorization": f"Bearer {token}"},
        files=[
            ("files", (f"photo{i}.jpg", valid_jpeg, "image/jpeg"))
            for i in range(1, 4)
        ],
    )

    assert response.status_code == 201
    assert response.json()["incident_id"] == incident_id
    assert response.json()["uploaded_count"] == 3
    assert len(response.json()["photos"]) == 3

    photo_count = (
        db_session.query(IncidentPhoto)
        .filter(IncidentPhoto.incident_id == incident_id)
        .count()
    )
    assert photo_count == 3

    incident = db_session.get(Incident, incident_id)
    assert incident is not None
    assert incident.status == "REPORTED"

    # Exactly three files should have been written.
    assert len(list(tmp_path.iterdir())) == 3
@pytest.mark.asyncio
async def test_photo_upload_rejects_reported_incident(
    api_client, db_session, citizen, citizen_incident
):
    incident_id = citizen_incident.id
    citizen_incident.status = "REPORTED"
    db_session.commit()

    token = create_access_token(
        citizen.id,
        token_version=citizen.token_version,
    )

    response = await api_client.post(
        f"/api/v1/incidents/{incident_id}/photos",
        headers={"Authorization": f"Bearer {token}"},
        files=[
            ("files", (f"photo{i}.jpg", b"unused", "image/jpeg"))
            for i in range(3)
        ],
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Photos can only be uploaded to an incident draft."
    )

@pytest.mark.asyncio
async def test_photo_upload_rejects_empty_file(
    api_client, db_session, citizen, citizen_incident
):
    incident_id = citizen_incident.id

    token = create_access_token(
        citizen.id,
        token_version=citizen.token_version,
    )
    db_session.commit()

    response = await api_client.post(
        f"/api/v1/incidents/{incident_id}/photos",
        headers={"Authorization": f"Bearer {token}"},
        files=[
            ("files", ("empty.jpg", b"", "image/jpeg")),
            ("files", ("photo2.jpg", b"unused", "image/jpeg")),
            ("files", ("photo3.jpg", b"unused", "image/jpeg")),
        ],
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "An uploaded photo is empty."

    incident = db_session.get(Incident, incident_id)
    assert incident is not None
    assert incident.status == "DRAFT"

    photo_count = (
        db_session.query(IncidentPhoto)
        .filter(IncidentPhoto.incident_id == incident_id)
        .count()
    )
    assert photo_count == 0

@pytest.mark.asyncio
async def test_photo_upload_rejects_gps_too_far_from_incident(
    api_client,
    db_session,
    citizen,
    citizen_incident,
    monkeypatch,
    tmp_path,
):
    from app.services import incident_photo as photo_service

    incident_id = citizen_incident.id

    monkeypatch.setattr(
        photo_service.settings,
        "INCIDENT_PHOTO_STORAGE_DIR",
        str(tmp_path),
    )

    # Simulate valid GPS metadata located well beyond 100 metres.
    monkeypatch.setattr(
        photo_service,
        "extract_photo_gps",
        lambda content: (34.0848, 74.7973),
    )

    image_buffer = BytesIO()
    Image.new("RGB", (10, 10), color="white").save(
        image_buffer,
        format="JPEG",
    )
    valid_jpeg = image_buffer.getvalue()

    token = create_access_token(
        citizen.id,
        token_version=citizen.token_version,
    )
    db_session.commit()

    response = await api_client.post(
        f"/api/v1/incidents/{incident_id}/photos",
        headers={"Authorization": f"Bearer {token}"},
        files=[
            ("files", (f"photo{i}.jpg", valid_jpeg, "image/jpeg"))
            for i in range(1, 4)
        ],
    )

    assert response.status_code == 422
    assert "too far from the incident location" in response.json()["detail"]

    incident = db_session.get(Incident, incident_id)
    assert incident is not None
    assert incident.status == "DRAFT"

    photo_count = (
        db_session.query(IncidentPhoto)
        .filter(IncidentPhoto.incident_id == incident_id)
        .count()
    )
    assert photo_count == 0
    assert list(tmp_path.iterdir()) == []

@pytest.mark.asyncio
async def test_official_without_jurisdiction_cannot_view_incident(
    api_client,
    db_session,
    citizen_incident,
):
    official = _make_user(
        db_session,
        "+919100000093",
        "OFFICIAL",
        assigned_district=None,
        assigned_tehsil=None,
    )
    db_session.commit()

    response = await api_client.get(
        f"/api/v1/incidents/{citizen_incident.id}",
        headers=_headers_for(official),
    )

    assert response.status_code == 403
