from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str

    APP_ENV: str = "development"

    OTP_PROVIDER: str = "console"
    OTP_HMAC_SECRET: str
    OTP_TTL_SECONDS: int = 300
    OTP_MAX_ATTEMPTS: int = 5

    JWT_SECRET_KEY: str
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_ISSUER: str = "resqgrid-api"
    JWT_AUDIENCE: str = "resqgrid-mobile"

    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    JWT_SESSION_ABSOLUTE_EXPIRE_DAYS: int = 30


    INCIDENT_PHOTO_STORAGE_DIR: str = "storage/incident_photos"
    INCIDENT_PHOTO_MAX_SIZE_BYTES: int = 10 * 1024 * 1024
    INCIDENT_PHOTO_MIN_COUNT: int = 3
    INCIDENT_PHOTO_MAX_COUNT: int = 10
    INCIDENT_PHOTO_MAX_DISTANCE_METERS: float = 100.0


    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
