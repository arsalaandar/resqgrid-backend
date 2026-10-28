import inspect
from io import BytesIO

import pytest
from PIL import Image
from PIL.TiffImagePlugin import IFDRational

from app.api.routes.incident_photos import upload_photos
from app.core.security import create_access_token
from app.models.incident import Incident
from app.models.incident_photo import IncidentPhoto
from app.models.user import User
from app.services import incident_photo as photo_service
from app.services.photo_gps import GPS_IFD_TAG, extract_photo_gps

LATITUDE = 34.0837
LONGITUDE = 74.7973


def jpeg_with_gps(size=(20, 20), orientation=None):
    """A JPEG whose EXIF GPS is within a few metres of the test incident."""
    image = Image.new("RGB", size, color="white")
    exif = Image.Exif()
    exif[GPS_IFD_TAG] = {
        1: "N",
        2: (IFDRational(34, 1), IFDRational(5, 1), IFDRational(1, 1)),
        3: "E",
        4: (IFDRational(74, 1), IFDRational(47, 1), IFDRational(50, 1)),
    }
    # Camera details that should also not survive storage.
    exif[0x010F] = "SecretCameraMaker"
    if orientation is not None:
        exif[0x0112] = orientation

    buffer = BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


@pytest.fixture
def citizen(db_session):
    user = User(
        phone="+919100000701",
        role="CITIZEN",
        is_active=True,
        is_verified=True,
        must_change_password=False,
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def draft_incident(db_session, citizen):
    incident = Incident(
        reporter_id=citizen.id,
        description="Flood water has entered the residential area.",
        latitude=LATITUDE,
        longitude=LONGITUDE,
        district="Srinagar",
        tehsil="Srinagar North",
        status="DRAFT",
        departmental_details={},
    )
    db_session.add(incident)
    db_session.flush()
    db_session.commit()
    return incident


@pytest.fixture
def storage(monkeypatch, tmp_path):
    monkeypatch.setattr(
        photo_service.settings, "INCIDENT_PHOTO_STORAGE_DIR", str(tmp_path)
    )
    return tmp_path


def headers_for(user):
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def three_files(content, name="photo.jpg"):
    return [("files", (name, content, "image/jpeg")) for _ in range(3)]


def test_upload_route_is_not_a_coroutine():
    # A coroutine route would run blocking Pillow and database work on the
    # event loop and stall every other request.
    assert not inspect.iscoroutinefunction(upload_photos)


@pytest.mark.asyncio
async def test_stored_photos_have_no_exif_or_gps(
    auth_client, db_session, citizen, draft_incident, storage
):
    original = jpeg_with_gps()
    assert extract_photo_gps(original)  # the upload really is GPS-tagged

    response = await auth_client.post(
        f"/api/v1/incidents/{draft_incident.id}/photos",
        headers=headers_for(citizen),
        files=three_files(original),
    )

    assert response.status_code == 201

    stored = list(storage.iterdir())
    assert len(stored) == 3

    for path in stored:
        with Image.open(path) as image:
            exif = image.getexif()
            assert GPS_IFD_TAG not in exif
            assert 0x010F not in exif
            assert len(exif) == 0

    records = db_session.query(IncidentPhoto).all()
    assert {r.size_bytes for r in records} == {
        path.stat().st_size for path in stored
    }
    assert all(r.content_type == "image/jpeg" for r in records)


@pytest.mark.asyncio
async def test_orientation_is_applied_before_metadata_is_dropped(
    auth_client, citizen, draft_incident, storage
):
    # Orientation 6 means "rotate 90 degrees clockwise to display".
    tall_sensor_image = jpeg_with_gps(size=(40, 20), orientation=6)

    response = await auth_client.post(
        f"/api/v1/incidents/{draft_incident.id}/photos",
        headers=headers_for(citizen),
        files=three_files(tall_sensor_image),
    )

    assert response.status_code == 201

    for path in storage.iterdir():
        with Image.open(path) as image:
            assert image.size == (20, 40)


@pytest.mark.asyncio
async def test_image_exceeding_pixel_limit_is_rejected(
    auth_client, db_session, citizen, draft_incident, storage, monkeypatch
):
    monkeypatch.setattr(photo_service.settings, "INCIDENT_PHOTO_MAX_PIXELS", 100)

    response = await auth_client.post(
        f"/api/v1/incidents/{draft_incident.id}/photos",
        headers=headers_for(citizen),
        files=three_files(jpeg_with_gps(size=(20, 20))),
    )

    assert response.status_code == 422
    assert "dimensions" in response.json()["detail"]
    assert list(storage.iterdir()) == []
    db_session.expire_all()
    assert db_session.get(Incident, draft_incident.id).status == "DRAFT"


@pytest.mark.asyncio
async def test_decompression_bomb_returns_422_not_500(
    auth_client, citizen, draft_incident, storage, monkeypatch
):
    # Pillow raises DecompressionBombError once an image exceeds twice its
    # own limit. Shrink that limit so a tiny image triggers it.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10)

    response = await auth_client.post(
        f"/api/v1/incidents/{draft_incident.id}/photos",
        headers=headers_for(citizen),
        files=three_files(jpeg_with_gps(size=(20, 20))),
    )

    assert response.status_code == 422
    assert "dimensions" in response.json()["detail"]


@pytest.mark.asyncio
async def test_combined_upload_size_is_capped(
    auth_client, db_session, citizen, draft_incident, storage, monkeypatch
):
    content = jpeg_with_gps()
    monkeypatch.setattr(
        photo_service.settings,
        "INCIDENT_PHOTO_MAX_TOTAL_BYTES",
        len(content) * 2 + 1,
    )

    response = await auth_client.post(
        f"/api/v1/incidents/{draft_incident.id}/photos",
        headers=headers_for(citizen),
        files=three_files(content),
    )

    assert response.status_code == 413
    assert "combined size" in response.json()["detail"]
    assert list(storage.iterdir()) == []
    db_session.expire_all()
    assert db_session.get(Incident, draft_incident.id).status == "DRAFT"


@pytest.mark.asyncio
async def test_corrupt_png_returns_422(
    auth_client, citizen, draft_incident, storage
):
    buffer = BytesIO()
    Image.new("RGB", (30, 30), "red").save(buffer, format="PNG")
    png = bytearray(buffer.getvalue())
    # Corrupt the compressed image data but keep a valid PNG header.
    for index in range(len(png) // 2, len(png) - 20):
        png[index] ^= 0xFF

    response = await auth_client.post(
        f"/api/v1/incidents/{draft_incident.id}/photos",
        headers=headers_for(citizen),
        files=[
            ("files", ("a.png", bytes(png), "image/png")),
            ("files", ("b.png", bytes(png), "image/png")),
            ("files", ("c.png", bytes(png), "image/png")),
        ],
    )

    assert response.status_code in (415, 422)
