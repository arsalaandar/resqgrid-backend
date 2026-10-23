from fastapi import APIRouter, Depends, File, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.dependencies import get_db
from app.models.user import User
from app.services.incident_photo import upload_incident_photos

router = APIRouter(
    prefix="/api/v1/incidents",
    tags=["Incident Photos"],
)


class IncidentPhotoResponse(BaseModel):
    id: int
    incident_id: int
    original_filename: str
    content_type: str
    size_bytes: int

    model_config = ConfigDict(from_attributes=True)


class IncidentPhotoUploadResponse(BaseModel):
    incident_id: int
    uploaded_count: int
    photos: list[IncidentPhotoResponse]


@router.post(
    "/{incident_id}/photos",
    response_model=IncidentPhotoUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_photos(
    incident_id: int,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    photos = await upload_incident_photos(
        db=db,
        incident_id=incident_id,
        reporter_id=current_user.id,
        files=files,
    )

    return IncidentPhotoUploadResponse(
        incident_id=incident_id,
        uploaded_count=len(photos),
        photos=photos,
    )
