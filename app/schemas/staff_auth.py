from pydantic import BaseModel, ConfigDict, Field


class StaffLoginRequest(BaseModel):
    phone: str = Field(min_length=8, max_length=16)
    password: str = Field(min_length=1, max_length=1024)

    model_config = ConfigDict(extra="forbid")


class StaffLoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_expires_in: int
    user_id: int
    role: str
    designation: str | None = None
    department: str | None = None
    must_change_password: bool
