import logging
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.incident import Incident
from app.models.incident_photo import IncidentPhoto
from app.services.photo_gps import distance_meters, extract_photo_gps

logger = logging.getLogger(__name__)

ALLOWED_FORMATS = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}


async def upload_incident_photos(
    db: Session,
    incident_id: int,
    reporter_id: int,
    files: list[UploadFile],
) -> list[IncidentPhoto]:
    """Validate and store mandatory photos before reporting an incident."""

    min_count = settings.INCIDENT_PHOTO_MIN_COUNT
    max_count = settings.INCIDENT_PHOTO_MAX_COUNT

    if not min_count <= len(files) <= max_count:
        raise HTTPException(
            status_code=422,
            detail=f"Upload between {min_count} and {max_count} photos.",
        )

    # Lock the incident row to prevent concurrent uploads from both
    # submitting the same draft.
    incident = db.scalar(
        select(Incident)
        .where(
            Incident.id == incident_id,
            Incident.reporter_id == reporter_id,
        )
        .with_for_update()
    )

    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")

    if incident.status != "DRAFT":
        raise HTTPException(
            status_code=409,
            detail="Photos can only be uploaded to an incident draft.",
        )

    storage_dir = Path(settings.INCIDENT_PHOTO_STORAGE_DIR)
    storage_dir.mkdir(parents=True, exist_ok=True)

    written_paths: list[Path] = []
    photo_records: list[IncidentPhoto] = []
    committed = False

    try:
        for upload in files:
            content = await upload.read(settings.INCIDENT_PHOTO_MAX_SIZE_BYTES + 1)

            if not content:
                raise HTTPException(
                    status_code=422,
                    detail="An uploaded photo is empty.",
                )

            if len(content) > settings.INCIDENT_PHOTO_MAX_SIZE_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail="Each photo must be 10 MB or smaller.",
                )

            # Validate actual image content, not the supplied filename.
            try:
                with Image.open(BytesIO(content)) as image:
                    image_format = image.format
                    image.verify()
            except (
                UnidentifiedImageError,
                OSError,
                ValueError,
            ) as exc:
                raise HTTPException(
                    status_code=422,
                    detail="An uploaded file is not a valid image.",
                ) from exc

            if image_format not in ALLOWED_FORMATS:
                raise HTTPException(
                    status_code=415,
                    detail="Only JPEG, PNG and WEBP photos are allowed.",
                )

            # Require valid embedded EXIF GPS coordinates.
            try:
                photo_lat, photo_lon = extract_photo_gps(content)
            except ValueError as exc:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Photo rejected: valid embedded GPS coordinates "
                        "are required. Capture a new GPS-tagged photo."
                    ),
                ) from exc

            distance = distance_meters(
                incident.latitude,
                incident.longitude,
                photo_lat,
                photo_lon,
            )

            if distance > settings.INCIDENT_PHOTO_MAX_DISTANCE_METERS:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Photo rejected: its embedded GPS coordinates "
                        "are too far from the incident location."
                    ),
                )

            storage_key = f"{uuid4().hex}.{image_format.lower()}"
            destination = storage_dir / storage_key

            # Exclusive creation prevents overwriting an existing file.
            with destination.open("xb") as output:
                output.write(content)

            written_paths.append(destination)

            photo_records.append(
                IncidentPhoto(
                    incident_id=incident_id,
                    storage_key=storage_key,
                    original_filename=Path(upload.filename or "incident_photo").name[
                        :255
                    ],
                    content_type=ALLOWED_FORMATS[image_format],
                    size_bytes=len(content),
                )
            )

        # Save photo records and update the incident status in one
        # database transaction.
        db.add_all(photo_records)
        incident.status = "REPORTED"
        db.commit()
        committed = True

        return photo_records

    except Exception:
        db.rollback()

        if not committed:
            for path in written_paths:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    logger.exception("Could not clean up a rejected photo.")

        raise

    finally:
        for upload in files:
            await upload.close()
