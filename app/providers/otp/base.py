from typing import Protocol


class OTPProvider(Protocol):
    def send_otp(self, phone: str, code: str) -> None:
        """Deliver an OTP to the specified phone number."""
        ...
