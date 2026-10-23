from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    reporter_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Existing report fields
    description: Mapped[str] = mapped_column(Text, nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="REPORTED",
        server_default="REPORTED",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Expanded report form fields.
    # Nullable initially so existing incident records remain valid.
    incident_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_drill: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    incident_datetime: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    district: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tehsil: Mapped[str | None] = mapped_column(String(100), nullable=True)
    incident_location: Mapped[str | None] = mapped_column(Text, nullable=True)
    incident_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    village_or_ward: Mapped[str | None] = mapped_column(String(200), nullable=True)

    damage_situation: Mapped[str | None] = mapped_column(String(100), nullable=True)
    severity_level: Mapped[str | None] = mapped_column(String(50), nullable=True)

    casualties: Mapped[int | None] = mapped_column(Integer, nullable=True)
    people_missing: Mapped[int | None] = mapped_column(Integer, nullable=True)
    minor_injuries: Mapped[int | None] = mapped_column(Integer, nullable=True)
    major_injuries: Mapped[int | None] = mapped_column(Integer, nullable=True)
    houses_completely_damaged: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    houses_partially_damaged: Mapped[int | None] = mapped_column(Integer, nullable=True)
    roads_damaged_over_50_percent: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )

    additional_remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    voice_message_required: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    medical_support_required: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True
    )

    # Structured answers from the departmental sections.
    departmental_details: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )

    __table_args__ = (
        Index(
            "ix_incidents_status_created_at",
            "status",
            "created_at",
        ),
    )
