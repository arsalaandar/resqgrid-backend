from pydantic import BaseModel, ConfigDict, Field, field_validator


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)

    model_config = ConfigDict(extra="forbid")

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("New password cannot be blank.")
        return value


class PasswordChangeResponse(BaseModel):
    message: str
    must_change_password: bool
