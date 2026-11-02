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
        METRICS_TOKEN="m" * 40,
    )
    assert config.APP_ENV == "production"


SAFE_EXCEPT_METRICS = {
    "OTP_PROVIDER": "sms",
    "RATE_LIMIT_STORAGE_URI": "redis://localhost:6379/0",
}


def test_metrics_token_is_optional_in_development():
    assert build().METRICS_TOKEN is None


@pytest.mark.parametrize("env", ["staging", "production"])
def test_metrics_token_is_required_outside_development(env):
    with pytest.raises(ValidationError, match="METRICS_TOKEN is required"):
        build(APP_ENV=env, **SAFE_EXCEPT_METRICS)


@pytest.mark.parametrize("env", ["staging", "production"])
def test_metrics_token_is_not_required_when_metrics_are_disabled(env):
    config = build(APP_ENV=env, METRICS_ENABLED=False, **SAFE_EXCEPT_METRICS)
    assert config.METRICS_TOKEN is None


def test_short_metrics_token_is_rejected():
    with pytest.raises(ValidationError):
        build(METRICS_TOKEN="short")


@pytest.mark.parametrize(
    "reused_secret",
    ["b" * 40, "a" * 40],  # the JWT secret, then the OTP secret, from VALID
)
def test_metrics_token_must_not_reuse_another_secret(reused_secret):
    with pytest.raises(ValidationError, match="must be different from"):
        build(
            APP_ENV="production",
            METRICS_TOKEN=reused_secret,
            **SAFE_EXCEPT_METRICS,
        )
