from app.core.config import settings
from app.providers.otp.base import OTPProvider
from app.providers.otp.console import ConsoleOTPProvider


def get_otp_provider() -> OTPProvider:
    if settings.OTP_PROVIDER == "console":
        if settings.APP_ENV != "development":
            raise RuntimeError("Console OTP provider is only allowed in development.")

        return ConsoleOTPProvider()

    raise RuntimeError(f"Unsupported OTP provider: {settings.OTP_PROVIDER}")
