"""Edge-case tests for OTP provider selection."""

import pytest

from app.core.config import settings
from app.providers.otp import factory
from app.providers.otp.console import ConsoleOTPProvider


def test_console_provider_selected_in_development(monkeypatch):
    monkeypatch.setattr(settings, "OTP_PROVIDER", "console")
    monkeypatch.setattr(settings, "APP_ENV", "development")

    provider = factory.get_otp_provider()

    assert isinstance(provider, ConsoleOTPProvider)


def test_console_provider_rejected_outside_development(monkeypatch):
    monkeypatch.setattr(settings, "OTP_PROVIDER", "console")
    monkeypatch.setattr(settings, "APP_ENV", "production")

    with pytest.raises(
        RuntimeError,
        match="Console OTP provider is only allowed in development",
    ):
        factory.get_otp_provider()


@pytest.mark.parametrize(
    "environment",
    ["production", "staging", "testing", "", "Development"],
)
def test_console_provider_rejected_for_every_non_development_environment(
    monkeypatch,
    environment,
):
    monkeypatch.setattr(settings, "OTP_PROVIDER", "console")
    monkeypatch.setattr(settings, "APP_ENV", environment)

    with pytest.raises(
        RuntimeError,
        match="Console OTP provider is only allowed in development",
    ):
        factory.get_otp_provider()


@pytest.mark.parametrize(
    "provider_name",
    ["", "sms", "twilio", "CONSOLE", "Console", "unknown"],
)
def test_unsupported_provider_configuration_fails_closed(
    monkeypatch,
    provider_name,
):
    monkeypatch.setattr(settings, "OTP_PROVIDER", provider_name)
    monkeypatch.setattr(settings, "APP_ENV", "development")

    with pytest.raises(
        RuntimeError,
        match=f"Unsupported OTP provider: {provider_name}",
    ):
        factory.get_otp_provider()


def test_console_provider_in_development_returns_new_instance(monkeypatch):
    monkeypatch.setattr(settings, "OTP_PROVIDER", "console")
    monkeypatch.setattr(settings, "APP_ENV", "development")

    first = factory.get_otp_provider()
    second = factory.get_otp_provider()

    assert isinstance(first, ConsoleOTPProvider)
    assert isinstance(second, ConsoleOTPProvider)
    assert first is not second
