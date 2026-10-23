from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AdminIncidentItem(BaseModel):
    id: int
    reporter_id: int
    reporter_phone: str | None
    reporter_role: str
    reporter_designation: str | None

    description: str
    latitude: float
    longitude: float
    status: str
    created_at: datetime

    incident_category: str | None
    is_drill: bool | None
    incident_datetime: datetime | None
    district: str | None
    tehsil: str | None
    incident_location: str | None
    incident_details: str | None
    village_or_ward: str | None
    damage_situation: str | None
    severity_level: str | None

    casualties: int | None
    people_missing: int | None
    minor_injuries: int | None
    major_injuries: int | None
    houses_completely_damaged: int | None
    houses_partially_damaged: int | None
    roads_damaged_over_50_percent: int | None

    additional_remarks: str | None
    voice_message_required: bool | None
    medical_support_required: bool | None
    departmental_details: dict

    model_config = ConfigDict(from_attributes=True)


class AdminIncidentListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[AdminIncidentItem]
