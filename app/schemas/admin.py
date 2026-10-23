import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.incident_options import DISTRICT_TEHSILS

PHONE_PATTERN = re.compile(r"^\+[1-9]\d{7,14}$")


class AdminAccountCreate(BaseModel):
    phone: str
    password: str = Field(min_length=12, max_length=1024)
    designation: str = Field(default="Administrator", min_length=2, max_length=100)
    department: str = Field(default="Disaster Management", min_length=2, max_length=100)

    model_config = ConfigDict(extra="forbid")

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        value = value.strip()
        if not PHONE_PATTERN.fullmatch(value):
            raise ValueError(
                "Use international phone format, e.g. +91 followed by the number."
            )
        return value


class OfficialAccountCreate(BaseModel):
    phone: str
    password: str = Field(min_length=12, max_length=1024)
    designation: str = Field(min_length=2, max_length=100)
    department: str = Field(min_length=2, max_length=100)
    assigned_district: str
    assigned_tehsil: str

    model_config = ConfigDict(extra="forbid")

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        value = value.strip()
        if not PHONE_PATTERN.fullmatch(value):
            raise ValueError(
                "Use international phone format, e.g. +91 followed by the number."
            )
        return value

    @field_validator("assigned_district")
    @classmethod
    def validate_district(cls, value: str) -> str:
        value = value.strip()
        if value not in DISTRICT_TEHSILS:
            raise ValueError("Invalid district.")
        return value

    @field_validator("assigned_tehsil")
    @classmethod
    def validate_tehsil(cls, value: str, info) -> str:
        value = value.strip()
        district = info.data.get("assigned_district")

        if district is None or value not in DISTRICT_TEHSILS.get(district, []):
            raise ValueError("Tehsil does not belong to the selected district.")

        return value


class ManagedAccountResponse(BaseModel):
    id: int
    phone: str | None
    role: str
    designation: str | None
    department: str | None
    assigned_district: str | None
    assigned_tehsil: str | None
    must_change_password: bool
    is_active: bool
    created_by_id: int | None

    model_config = ConfigDict(from_attributes=True)
