from datetime import datetime
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.core.incident_options import (
    DAMAGE_SITUATIONS,
    DISTRICT_TEHSILS,
    INCIDENT_CATEGORIES,
    INCIDENT_SEVERITY_LEVELS,
)


class DepartmentalDetails(BaseModel):
    """Department-specific support information from the incident form."""

    medical_care_public_health: dict[str, Any] = Field(default_factory=dict)
    sanitation_sewerage: dict[str, Any] = Field(default_factory=dict)
    power_electricity: dict[str, Any] = Field(default_factory=dict)
    transport: dict[str, Any] = Field(default_factory=dict)
    search_and_rescue: dict[str, Any] = Field(default_factory=dict)
    public_works_engineering: dict[str, Any] = Field(default_factory=dict)
    food_and_supplies: dict[str, Any] = Field(default_factory=dict)
    drinking_water: dict[str, Any] = Field(default_factory=dict)
    relief_camps: dict[str, Any] = Field(default_factory=dict)
    law_order_traffic: dict[str, Any] = Field(default_factory=dict)
    flood_water_control: dict[str, Any] = Field(default_factory=dict)
    evacuation: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class IncidentCreate(BaseModel):
    # Main incident information
    incident_category: str
    is_drill: bool
    incident_datetime: datetime

    district: str
    tehsil: str
    incident_location: str | None = Field(default=None, max_length=500)
    description: str = Field(min_length=10, max_length=2000)
    incident_details: str | None = Field(default=None, max_length=5000)
    village_or_ward: str | None = Field(default=None, max_length=200)

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)

    # Impact and damage
    damage_situation: str
    severity_level: str

    casualties: int = Field(default=0, ge=0)
    people_missing: int = Field(default=0, ge=0)
    minor_injuries: int = Field(default=0, ge=0)
    major_injuries: int = Field(default=0, ge=0)
    houses_completely_damaged: int = Field(default=0, ge=0)
    houses_partially_damaged: int = Field(default=0, ge=0)
    roads_damaged_over_50_percent: int = Field(default=0, ge=0)

    additional_remarks: str = Field(min_length=1, max_length=5000)
    voice_message_required: bool = False
    medical_support_required: bool = False

    # Departmental questions from the supplied form
    departmental_details: DepartmentalDetails = Field(
        default_factory=DepartmentalDetails
    )

    model_config = ConfigDict(extra="forbid")

    @field_validator("incident_category")
    @classmethod
    def validate_incident_category(cls, value: str) -> str:
        if value not in INCIDENT_CATEGORIES:
            raise ValueError("Invalid incident category.")
        return value

    @field_validator("damage_situation")
    @classmethod
    def validate_damage_situation(cls, value: str) -> str:
        if value not in DAMAGE_SITUATIONS:
            raise ValueError("Invalid damage situation.")
        return value

    @field_validator("severity_level")
    @classmethod
    def validate_severity_level(cls, value: str) -> str:
        if value not in INCIDENT_SEVERITY_LEVELS:
            raise ValueError("Invalid incident severity level.")
        return value

    @model_validator(mode="after")
    def validate_district_tehsil(self):
        allowed_tehsils = DISTRICT_TEHSILS.get(self.district)

        if allowed_tehsils is None:
            raise ValueError("Invalid district.")

        if self.tehsil not in allowed_tehsils:
            raise ValueError(
                "The selected tehsil does not belong to the selected district."
            )

        return self


class IncidentResponse(BaseModel):
    id: int
    reporter_id: int
    incident_category: str | None
    is_drill: bool | None
    incident_datetime: datetime | None
    district: str | None
    tehsil: str | None
    description: str
    latitude: float
    longitude: float
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
