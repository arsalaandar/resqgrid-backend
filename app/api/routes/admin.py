from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.passwords import hash_password
from app.core.permissions import require_roles
from app.db.dependencies import get_db
from app.models.incident import Incident
from app.models.user import User
from app.schemas.admin import (
    AdminAccountCreate,
    ManagedAccountResponse,
    OfficialAccountCreate,
)
from app.schemas.admin_incidents import (
    AdminIncidentItem,
    AdminIncidentListResponse,
)

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["Admin"],
)


@router.get("/check-access")
def check_admin_access(
    current_user: User = Depends(require_roles("SUPER_ADMIN", "ADMIN")),
):
    return {
        "message": "Admin access granted",
        "user_id": current_user.id,
        "role": current_user.role.upper(),
    }


@router.post(
    "/admins",
    response_model=ManagedAccountResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_admin(
    payload: AdminAccountCreate,
    current_user: User = Depends(require_roles("SUPER_ADMIN")),
    db: Session = Depends(get_db),
):
    existing = db.scalar(select(User.id).where(User.phone == payload.phone))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this phone number already exists.",
        )

    account = User(
        phone=payload.phone,
        password_hash=hash_password(payload.password),
        role="ADMIN",
        designation=payload.designation,
        department=payload.department,
        assigned_district=None,
        assigned_tehsil=None,
        must_change_password=True,
        created_by_id=current_user.id,
        is_active=True,
        is_verified=True,
    )

    try:
        db.add(account)
        db.commit()
        db.refresh(account)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this phone number already exists.",
        ) from exc

    return account


@router.post(
    "/officials",
    response_model=ManagedAccountResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_official(
    payload: OfficialAccountCreate,
    current_user: User = Depends(require_roles("SUPER_ADMIN", "ADMIN")),
    db: Session = Depends(get_db),
):
    existing = db.scalar(select(User.id).where(User.phone == payload.phone))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this phone number already exists.",
        )

    account = User(
        phone=payload.phone,
        password_hash=hash_password(payload.password),
        role="OFFICIAL",
        designation=payload.designation,
        department=payload.department,
        assigned_district=payload.assigned_district,
        assigned_tehsil=payload.assigned_tehsil,
        must_change_password=True,
        created_by_id=current_user.id,
        is_active=True,
        is_verified=True,
    )

    try:
        db.add(account)
        db.commit()
        db.refresh(account)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this phone number already exists.",
        ) from exc

    return account


@router.get(
    "/incidents",
    response_model=AdminIncidentListResponse,
)
def list_state_incidents(
    status_filter: str | None = Query(default=None, alias="status"),
    district: str | None = Query(default=None, max_length=100),
    tehsil: str | None = Query(default=None, max_length=100),
    category: str | None = Query(default=None, max_length=100),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(require_roles("SUPER_ADMIN", "ADMIN")),
    db: Session = Depends(get_db),
):
    # Build one reusable filtered query.
    filters = []

    if status_filter:
        filters.append(Incident.status == status_filter.strip().upper())

    if district:
        filters.append(Incident.district.ilike(district.strip()))

    if tehsil:
        filters.append(Incident.tehsil.ilike(tehsil.strip()))

    if category:
        filters.append(Incident.incident_category.ilike(category.strip()))

    if date_from:
        filters.append(Incident.created_at >= date_from)

    if date_to:
        filters.append(Incident.created_at <= date_to)

    # Count matching incidents before pagination.
    count_statement = select(func.count(Incident.id)).where(*filters)
    total = db.scalar(count_statement) or 0

    # Fetch incidents together with their reporter's public details.
    statement = (
        select(Incident, User)
        .join(User, User.id == Incident.reporter_id)
        .where(*filters)
        .order_by(Incident.created_at.desc(), Incident.id.desc())
        .limit(limit)
        .offset(offset)
    )

    rows = db.execute(statement).all()

    items = []

    for incident, reporter in rows:
        items.append(
            AdminIncidentItem(
                id=incident.id,
                reporter_id=incident.reporter_id,
                reporter_phone=reporter.phone,
                reporter_role=reporter.role.upper(),
                reporter_designation=reporter.designation,
                description=incident.description,
                latitude=incident.latitude,
                longitude=incident.longitude,
                status=incident.status,
                created_at=incident.created_at,
                incident_category=incident.incident_category,
                is_drill=incident.is_drill,
                incident_datetime=incident.incident_datetime,
                district=incident.district,
                tehsil=incident.tehsil,
                incident_location=incident.incident_location,
                incident_details=incident.incident_details,
                village_or_ward=incident.village_or_ward,
                damage_situation=incident.damage_situation,
                severity_level=incident.severity_level,
                casualties=incident.casualties,
                people_missing=incident.people_missing,
                minor_injuries=incident.minor_injuries,
                major_injuries=incident.major_injuries,
                houses_completely_damaged=(incident.houses_completely_damaged),
                houses_partially_damaged=(incident.houses_partially_damaged),
                roads_damaged_over_50_percent=(incident.roads_damaged_over_50_percent),
                additional_remarks=incident.additional_remarks,
                voice_message_required=(incident.voice_message_required),
                medical_support_required=(incident.medical_support_required),
                departmental_details=(incident.departmental_details or {}),
            )
        )

    return AdminIncidentListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=items,
    )
