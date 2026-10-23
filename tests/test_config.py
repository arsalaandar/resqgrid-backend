import pytest
from pydantic import ValidationError

from app.core.config import Settings

VALID = {
    "DATABASE_URL": "postgresql+psycopg://u:p@localhost:5432/db",
    "OTP_HMAC_SECRET": "a" * 40,
    "JWT_SECRET_KEY": "b" * 40,
    "APP_ENV": "development",
}


def build(**overrides):
    # _env_file=None stops a developer's real .env from leaking into the test.
    return Settings(_env_file=None, **{**VALID, **overrides})


def test_valid_development_settings_load():
    assert build().APP_ENV == "development"


def test_rate_limit_storage_defaults_to_memory():
    assert build().RATE_LIMIT_STORAGE_URI == "memory://"


def test_identical_secrets_are_rejected():
    with pytest.raises(ValidationError, match="must be different"):
        build(OTP_HMAC_SECRET="c" * 40, JWT_SECRET_KEY="c" * 40)


@pytest.mark.parametrize("field", ["OTP_HMAC_SECRET", "JWT_SECRET_KEY"])
def test_short_secrets_are_rejected(field):
    with pytest.raises(ValidationError):
        build(**{field: "short"})


def test_unknown_environment_is_rejected():
    with pytest.raises(ValidationError):
        build(APP_ENV="prod")


def test_session_lifetime_shorter_than_refresh_is_rejected():
    with pytest.raises(ValidationError, match="SESSION_ABSOLUTE"):
        build(
            JWT_REFRESH_TOKEN_EXPIRE_DAYS=10,
            JWT_SESSION_ABSOLUTE_EXPIRE_DAYS=5,
        )


@pytest.mark.parametrize("env", ["staging", "production"])
def test_console_otp_is_rejected_outside_development(env):
    with pytest.raises(ValidationError, match="console OTP"):
        build(
            APP_ENV=env,
            OTP_PROVIDER="console",
            RATE_LIMIT_STORAGE_URI="redis://localhost:6379/0",
        )


@pytest.mark.parametrize("env", ["staging", "production"])
def test_memory_rate_limit_storage_is_rejected_outside_development(env):
    with pytest.raises(ValidationError, match="rate-limit storage"):
        build(APP_ENV=env, OTP_PROVIDER="sms")


def test_production_with_safe_settings_loads():
    config = build(
        APP_ENV="production",
        OTP_PROVIDER="sms",
        RATE_LIMIT_STORAGE_URI="redis://localhost:6379/0",
    )
    assert config.APP_ENV == "production"
