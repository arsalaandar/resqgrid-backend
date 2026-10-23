from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str

    APP_ENV: Literal["development", "testing", "staging", "production"] = (
        "development"
    )

    OTP_PROVIDER: str = "console"
    OTP_HMAC_SECRET: str = Field(min_length=32)
    OTP_TTL_SECONDS: int = 300
    OTP_MAX_ATTEMPTS: int = 5

    JWT_SECRET_KEY: str = Field(min_length=32)
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_ISSUER: str = "resqgrid-api"
    JWT_AUDIENCE: str = "resqgrid-mobile"

    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    JWT_SESSION_ABSOLUTE_EXPIRE_DAYS: int = 30

    # "memory://" is per-process and only suitable for development and tests.
    # Use a shared store such as redis://host:6379/0 for multiple workers.
    RATE_LIMIT_STORAGE_URI: str = "memory://"

    INCIDENT_PHOTO_STORAGE_DIR: str = "storage/incident_photos"
    INCIDENT_PHOTO_MAX_SIZE_BYTES: int = 10 * 1024 * 1024
    INCIDENT_PHOTO_MIN_COUNT: int = 3
    INCIDENT_PHOTO_MAX_COUNT: int = 10
    INCIDENT_PHOTO_MAX_DISTANCE_METERS: float = 100.0

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_security_settings(self):
        if self.JWT_SECRET_KEY == self.OTP_HMAC_SECRET:
            raise ValueError(
                "JWT_SECRET_KEY and OTP_HMAC_SECRET must be different."
            )

        if (
            self.JWT_SESSION_ABSOLUTE_EXPIRE_DAYS
            < self.JWT_REFRESH_TOKEN_EXPIRE_DAYS
        ):
            raise ValueError(
                "JWT_SESSION_ABSOLUTE_EXPIRE_DAYS must be greater than or "
                "equal to JWT_REFRESH_TOKEN_EXPIRE_DAYS."
            )

        if self.APP_ENV in ("staging", "production"):
            if self.OTP_PROVIDER == "console":
                raise ValueError(
                    "The console OTP provider is not allowed in this "
                    "environment."
                )

            if self.RATE_LIMIT_STORAGE_URI.startswith("memory://"):
                raise ValueError(
                    "Shared rate-limit storage (for example redis://) is "
                    "required in this environment."
                )

        return self


settings = Settings()
