from sqlalchemy.orm import Session

from app.models.incident import Incident
from app.schemas.incident import IncidentCreate


def create_incident(
    db: Session,
    reporter_id: int,
    payload: IncidentCreate,
) -> Incident:
    """Create an incident draft awaiting mandatory photo validation."""

    data = payload.model_dump()
    data["departmental_details"] = payload.departmental_details.model_dump()

    incident = Incident(
        reporter_id=reporter_id,
        status="DRAFT",
        **data,
    )

    try:
        db.add(incident)
        db.commit()
        db.refresh(incident)
        return incident
    except Exception:
        db.rollback()
        raise
