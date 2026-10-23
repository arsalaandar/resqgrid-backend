from pydantic import BaseModel, Field


class OTPRequest(BaseModel):
    phone: str = Field(pattern=r"^\+[1-9]\d{7,14}$")


class OTPVerify(BaseModel):
    phone: str = Field(pattern=r"^\+[1-9]\d{7,14}$")

    code: str = Field(pattern=r"^\d{6}$")


class OTPMessageResponse(BaseModel):
    message: str


class CitizenLoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_expires_in: int
    user_id: int
    role: str
