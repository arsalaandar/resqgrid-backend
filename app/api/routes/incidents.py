from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.incident_options import (
    DAMAGE_SITUATIONS,
    DISTRICT_TEHSILS,
    INCIDENT_CATEGORIES,
    INCIDENT_SEVERITY_LEVELS,
)
from app.core.roles import ADMIN_ROLES, Role
from app.db.dependencies import get_db
from app.models.incident import Incident
from app.models.user import User
from app.schemas.incident import IncidentCreate, IncidentResponse
from app.services.incident import create_incident

router = APIRouter(
    prefix="/api/v1/incidents",
    tags=["Incidents"],
)


def _visible_to_official(user: User):
    """Officials see submitted incidents, plus any draft they wrote themselves.

    A DRAFT has no photos and has not been reported yet, so another person's
    draft is not something a field official should see or act on.
    """
    return or_(Incident.status != "DRAFT", Incident.reporter_id == user.id)


@router.post(
    "",
    response_model=IncidentResponse,
    status_code=status.HTTP_201_CREATED,
)
def report_incident(
    payload: IncidentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role.upper() == Role.OFFICIAL:
        if not current_user.assigned_district or not current_user.assigned_tehsil:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account has no assigned jurisdiction.",
            )

        if (
            payload.district.casefold() != current_user.assigned_district.casefold()
            or payload.tehsil.casefold() != current_user.assigned_tehsil.casefold()
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only report incidents within your assigned"
                "district and tehsil.",
            )
    incident = create_incident(
        db=db,
        reporter_id=current_user.id,
        payload=payload,
    )
    return incident


@router.get("/my", response_model=list[IncidentResponse])
def get_my_incidents(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    statement = (
        select(Incident)
        .where(Incident.reporter_id == current_user.id)
        .order_by(Incident.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    return db.scalars(statement).all()


@router.get("/assigned", response_model=list[IncidentResponse])
def get_assigned_incidents(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role.upper() != Role.OFFICIAL:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is for field officials only.",
        )

    if not current_user.assigned_district or not current_user.assigned_tehsil:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has no assigned jurisdiction.",
        )

    statement = (
        select(Incident)
        .where(
            func.lower(Incident.district) == current_user.assigned_district.casefold(),
            func.lower(Incident.tehsil) == current_user.assigned_tehsil.casefold(),
            _visible_to_official(current_user),
        )
        .order_by(
            Incident.created_at.desc(),
            Incident.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    )

    return db.scalars(statement).all()


@router.get("/options")
def get_incident_options():
    """Return the configured options for the incident form."""

    return {
        "incident_categories": INCIDENT_CATEGORIES,
        "damage_situations": DAMAGE_SITUATIONS,
        "severity_levels": INCIDENT_SEVERITY_LEVELS,
        "districts": list(DISTRICT_TEHSILS.keys()),
    }


@router.get("/options/tehsils")
def get_tehsils(
    district: str = Query(..., min_length=1),
):
    """Return tehsils belonging to the selected district."""

    tehsils = DISTRICT_TEHSILS.get(district)

    if tehsils is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid district.",
        )

    return {
        "district": district,
        "tehsils": list(dict.fromkeys(tehsils)),
    }


@router.get("/{incident_id}", response_model=IncidentResponse)
def get_incident(
    incident_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    role = current_user.role.upper()

    statement = select(Incident).where(Incident.id == incident_id)

    if role == Role.CITIZEN:
        statement = statement.where(Incident.reporter_id == current_user.id)

    elif role == Role.OFFICIAL:
        if not current_user.assigned_district or not current_user.assigned_tehsil:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account has no assigned jurisdiction.",
            )

        statement = statement.where(
            func.lower(Incident.district) == current_user.assigned_district.casefold(),
            func.lower(Incident.tehsil) == current_user.assigned_tehsil.casefold(),
            _visible_to_official(current_user),
        )

    elif role not in ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view this incident.",
        )

    incident = db.scalar(statement)

    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Incident not found.",
        )

    return incident
