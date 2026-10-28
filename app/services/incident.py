from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
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


def purge_stale_drafts(db: Session, older_than_days: int = 7) -> int:
    """Delete DRAFT incidents that were never completed with photos.

    Drafts become REPORTED only when valid photos are uploaded, so an old
    draft is an abandoned report. Returns the number of rows deleted.
    """
    if older_than_days < 1:
        raise ValueError("older_than_days must be at least 1.")

    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)

    try:
        result = db.execute(
            delete(Incident).where(
                Incident.status == "DRAFT",
                Incident.created_at < cutoff,
            )
        )
        db.commit()
        return result.rowcount or 0
    except Exception:
        db.rollback()
        raise
